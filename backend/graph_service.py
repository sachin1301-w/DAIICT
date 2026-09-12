"""
Graph-based fraud detection over the REC ownership/transfer graph.

Nodes = entities (generators, brokers, traders, companies). Edges = REC
transfers. Rebuilt from `rec_transactions` on every call, since the graph
changes continuously as the simulator runs.

NOTE: ISSUE events are deliberately NOT turned into edges from a shared
"origin" node -- doing that would connect every unrelated plant through one
hub and merge clean, unrelated ownership chains into a single false
"cluster". Only TRANSFER edges count toward clustering/cycle/density
analysis (verified against a real bug hit during an earlier iteration of
this project).
"""
from __future__ import annotations

import itertools
import time
from collections import defaultdict

import networkx as nx
from sqlalchemy.orm import Session

import models

RAPID_TRANSFER_WINDOW_SECONDS = 60 * 60 * 6  # 6 hours
HIGH_DEGREE_THRESHOLD = 4

GRAPH_SCORE_WEIGHTS = {
    "circular_ownership": 35,
    "dense_suspicious_cluster": 25,
    "rapid_transfer_chain": 20,
    "high_degree_hub": 10,
    "repeated_edges": 10,
}


def _classify_entity(entity_id: str) -> str:
    """Best-effort node type classification for display/DB purposes -- entity
    ids are either a generator's synthetic id, a wallet label like
    'Trader: Broker X', a raw 0x address, or a simulator-invented company
    name. There's no strict registry for the last case, so this is a
    heuristic, not authoritative."""
    lowered = entity_id.lower()
    if entity_id.startswith("GEN-") or "generator" in lowered:
        return "GENERATOR"
    if "broker" in lowered:
        return "BROKER"
    if "trader" in lowered or "company" in lowered:
        return "TRADER"
    if entity_id.startswith("0x"):
        return "WALLET"
    return "COMPANY"


class GraphFraudEngine:
    def __init__(self):
        self.graph = nx.MultiDiGraph()

    # ---------------- build ----------------

    def reset(self) -> None:
        """Drop all in-memory graph state. `build()` already rebuilds the
        graph from scratch on every call (see module docstring), so this is
        mostly belt-and-braces for the moment right after a data reset,
        before anything has called build() again -- callers that read
        `self.graph` directly (rather than through build()) still see an
        empty graph instead of the previous run's stale state."""
        self.graph = nx.MultiDiGraph()

    def build(self, db: Session) -> None:
        self.graph = nx.MultiDiGraph()
        transactions = db.query(models.RECTransaction).order_by(models.RECTransaction.transaction_timestamp).all()
        for tx in transactions:
            if tx.transaction_type == "TRANSFER" and tx.sender and tx.receiver:
                self.graph.add_node(tx.sender)
                self.graph.add_node(tx.receiver)
                self.graph.add_edge(
                    tx.sender, tx.receiver,
                    rec_id=tx.rec_id, timestamp=tx.transaction_timestamp, transaction_id=tx.transaction_id,
                )
            elif tx.transaction_type == "ISSUE" and tx.receiver:
                self.graph.add_node(tx.receiver)

    # ---------------- entity-level metrics ----------------

    def entity_metrics(self) -> dict[str, dict]:
        if self.graph.number_of_nodes() == 0:
            return {}
        undirected = nx.Graph(self.graph)
        betweenness = nx.betweenness_centrality(undirected) if undirected.number_of_nodes() > 2 else {n: 0 for n in undirected}
        closeness = nx.closeness_centrality(undirected)
        clustering = nx.clustering(undirected)
        metrics = {}
        for n in self.graph.nodes():
            metrics[n] = {
                "degree": self.graph.in_degree(n) + self.graph.out_degree(n),
                "in_degree": self.graph.in_degree(n),
                "out_degree": self.graph.out_degree(n),
                "betweenness_centrality": round(betweenness.get(n, 0), 4),
                "closeness_centrality": round(closeness.get(n, 0), 4),
                "clustering_coefficient": round(clustering.get(n, 0), 4),
            }
        return metrics

    def sync_entities_to_db(self, db: Session) -> None:
        """Persists per-entity graph metrics into graph_entities (upsert by
        entity_id), same rationale as sync_clusters_to_db: the graph is
        rebuilt live on every call, this just keeps a queryable snapshot."""
        metrics = self.entity_metrics()
        for entity_id, m in metrics.items():
            row = db.query(models.GraphEntity).filter_by(entity_id=entity_id).first()
            if row is None:
                row = models.GraphEntity(entity_id=entity_id, entity_type=_classify_entity(entity_id))
                db.add(row)
            row.degree = m["degree"]
            row.betweenness = m["betweenness_centrality"]
            row.risk_score = min(m["degree"] * 10 + m["betweenness_centrality"] * 100, 100)
        db.commit()

    # ---------------- individual detectors ----------------

    def circular_ownership(self) -> list[list[str]]:
        simple = nx.DiGraph(self.graph)
        return [c for c in nx.simple_cycles(simple) if len(c) > 1]

    def repeated_transfer_pairs(self) -> dict[tuple[str, str], int]:
        counts: dict[tuple[str, str], int] = defaultdict(int)
        for u, v in self.graph.edges():
            counts[(u, v)] += 1
        return {pair: c for pair, c in counts.items() if c > 1}

    def high_degree_hubs(self, threshold: int = HIGH_DEGREE_THRESHOLD) -> list[str]:
        return [n for n in self.graph.nodes() if self.graph.in_degree(n) + self.graph.out_degree(n) >= threshold]

    def rapid_transfer_chains(self, window_seconds: float = RAPID_TRANSFER_WINDOW_SECONDS) -> list[list[str]]:
        simple = nx.DiGraph()
        for u, v, data in self.graph.edges(data=True):
            if simple.has_edge(u, v):
                simple[u][v]["timestamps"].append(data["timestamp"])
            else:
                simple.add_edge(u, v, timestamps=[data["timestamp"]])

        chains = []
        for start in simple.nodes():
            path, node, visited = [start], start, set()
            while True:
                candidates = [(v, min(d["timestamps"])) for v, d in simple[node].items() if (node, v) not in visited]
                if not candidates:
                    break
                nxt, ts = min(candidates, key=lambda c: c[1])
                if len(path) > 1:
                    prev_ts = simple[path[-2]][path[-1]]["timestamps"][0]
                    if ts - prev_ts > window_seconds:
                        break
                visited.add((node, nxt))
                path.append(nxt)
                node = nxt
                if len(path) > 8:
                    break
            if len(path) >= 4:
                chains.append(path)
        return chains

    def communities(self) -> list[set[str]]:
        undirected = nx.Graph(self.graph)
        if undirected.number_of_edges() == 0:
            return []
        try:
            return [set(c) for c in nx.algorithms.community.greedy_modularity_communities(undirected)]
        except Exception:
            return [set(c) for c in nx.connected_components(undirected)]

    # ---------------- cluster-level scoring ----------------

    def suspicious_clusters(self) -> list[dict]:
        undirected = nx.Graph(self.graph)
        cycles = self.circular_ownership()
        hubs = set(self.high_degree_hubs())
        repeated_pairs = self.repeated_transfer_pairs()
        chains = self.rapid_transfer_chains()

        clusters = []
        for i, component in enumerate(nx.connected_components(undirected)):
            if len(component) < 2:
                continue
            sub = self.graph.subgraph(component)
            entities = len(component)
            transfers = sub.number_of_edges()
            rec_ids = {d["rec_id"] for _, _, d in sub.edges(data=True)}

            has_cycle = any(set(c).issubset(component) for c in cycles)
            has_repeats = any(u in component and v in component for (u, v) in repeated_pairs)
            has_hub = bool(hubs & component)
            has_rapid_chain = any(set(chain) & component for chain in chains)

            # A plain ownership chain (tree) needs exactly (entities-1) transfers;
            # extra transfers beyond that indicate real density, not an artifact
            # of small-chain topology (see module docstring).
            extra_edges = transfers - (entities - 1)
            has_dense_cluster = entities >= 4 and extra_edges >= 2
            density = transfers / (entities * (entities - 1)) if entities > 1 else 0

            if not (has_cycle or has_repeats or has_hub or has_dense_cluster or has_rapid_chain):
                continue

            score = 0
            patterns = []
            if has_cycle:
                score += GRAPH_SCORE_WEIGHTS["circular_ownership"]
                patterns.append("Circular ownership")
            if has_dense_cluster:
                score += GRAPH_SCORE_WEIGHTS["dense_suspicious_cluster"]
                patterns.append("Dense suspicious cluster")
            if has_rapid_chain:
                score += GRAPH_SCORE_WEIGHTS["rapid_transfer_chain"]
                patterns.append("Rapid transfer chain")
            if has_hub:
                score += GRAPH_SCORE_WEIGHTS["high_degree_hub"]
                patterns.append("Unusually high-degree broker")
            if has_repeats:
                score += GRAPH_SCORE_WEIGHTS["repeated_edges"]
                patterns.append("Repeated transfers")

            clusters.append({
                "cluster_id": f"FRAUD-{i:03d}",
                "entities_involved": entities,
                "entity_ids": sorted(component),
                "recs_involved": len(rec_ids),
                "transfers_involved": transfers,
                "graph_score": min(score, 100),
                "risk_score": min(score, 100),
                "cluster_density": round(density, 3),
                "patterns": patterns,
            })

        clusters.sort(key=lambda c: c["graph_score"], reverse=True)
        return clusters

    def sync_clusters_to_db(self, db: Session, clusters: list[dict] | None = None) -> None:
        """Persists the live-computed clusters into fraud_clusters (upsert by
        cluster_id), and closes out any previously-recorded cluster that's no
        longer suspicious. Clusters are still computed live on every request
        (the graph changes every tick) -- this just keeps a queryable,
        historical record matching the fraud_clusters schema."""
        import json

        if clusters is None:
            clusters = self.suspicious_clusters()

        current_ids = set()
        for c in clusters:
            current_ids.add(c["cluster_id"])
            row = db.query(models.FraudCluster).filter_by(cluster_id=c["cluster_id"]).first()
            if row is None:
                row = models.FraudCluster(cluster_id=c["cluster_id"])
                db.add(row)
            row.entity_count = c["entities_involved"]
            row.rec_count = c["recs_involved"]
            row.transfer_count = c["transfers_involved"]
            row.graph_score = c["graph_score"]
            row.risk_score = c["risk_score"]
            row.fraud_pattern = json.dumps(c["patterns"])
            row.status = "ACTIVE"

        stale = db.query(models.FraudCluster).filter(
            models.FraudCluster.status == "ACTIVE", ~models.FraudCluster.cluster_id.in_(current_ids or [""])
        ).all()
        for row in stale:
            row.status = "RESOLVED"

        db.commit()

    def transaction_graph_features(self, source: str, target: str) -> dict:
        """Per-transaction graph features fed into ml_service.score_transaction."""
        metrics = self.entity_metrics()
        src_m = metrics.get(source, {"degree": 0, "betweenness_centrality": 0})
        tgt_m = metrics.get(target, {"degree": 0, "betweenness_centrality": 0})

        cycles = self.circular_ownership()
        cycle_count = sum(1 for c in cycles if source in c and target in c)

        community_size = 1
        for community in self.communities():
            if source in community or target in community:
                community_size = max(community_size, len(community))

        clusters = self.suspicious_clusters()
        cluster_density = 0.0
        repeated_edge_count = 0
        for cluster in clusters:
            if source in cluster["entity_ids"] or target in cluster["entity_ids"]:
                cluster_density = max(cluster_density, cluster["cluster_density"])
        repeated_pairs = self.repeated_transfer_pairs()
        repeated_edge_count = repeated_pairs.get((source, target), 0)

        return {
            "source_degree": src_m["degree"],
            "target_degree": tgt_m["degree"],
            "source_betweenness": src_m.get("betweenness_centrality", 0),
            "target_betweenness": tgt_m.get("betweenness_centrality", 0),
            "cycle_count": cycle_count,
            "community_size": community_size,
            "cluster_density": cluster_density,
            "repeated_edge_count": repeated_edge_count,
        }

    def as_visjs(self) -> dict:
        hubs = set(self.high_degree_hubs())
        cycle_nodes = set(itertools.chain.from_iterable(self.circular_ownership()))
        nodes = [
            {"id": n, "label": n, "group": "flagged" if (n in hubs or n in cycle_nodes) else "normal"}
            for n in self.graph.nodes()
        ]
        edges = [
            {"from": u, "to": v, "arrows": "to", "title": d.get("rec_id", "")}
            for u, v, d in self.graph.edges(data=True)
        ]
        return {"nodes": nodes, "edges": edges}


_engine = GraphFraudEngine()


def get_engine() -> GraphFraudEngine:
    return _engine
