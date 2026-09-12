import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";

export default function NetworkGraph({ focusEntities, onClearFocus }) {
  const containerRef = useRef(null);
  const networkRef = useRef(null);
  const [stats, setStats] = useState({ nodes: 0, edges: 0 });

  useEffect(() => {
    let cancelled = false;
    const focusSet = focusEntities ? new Set(focusEntities) : null;

    async function load() {
      const data = await api.networkGraph();
      if (cancelled || !containerRef.current || !window.vis) return;

      const visibleNodes = focusSet ? data.nodes.filter((n) => focusSet.has(n.id)) : data.nodes;
      const visibleEdges = focusSet
        ? data.edges.filter((e) => focusSet.has(e.from) && focusSet.has(e.to))
        : data.edges;

      const nodes = new window.vis.DataSet(
        visibleNodes.map((n) => ({
          id: n.id,
          label: n.label.length > 18 ? n.label.slice(0, 18) + "..." : n.label,
          color: n.group === "flagged" ? "#f87171" : "#34d399",
        }))
      );
      const edges = new window.vis.DataSet(visibleEdges);
      setStats({ nodes: visibleNodes.length, edges: visibleEdges.length });

      if (networkRef.current) networkRef.current.destroy();
      networkRef.current = new window.vis.Network(
        containerRef.current,
        { nodes, edges },
        {
          nodes: { shape: "dot", size: 16, font: { color: "#e2e8f0", size: 11 } },
          edges: { color: "#475569", smooth: true, arrows: "to" },
          physics: { stabilization: true },
        }
      );
    }

    load();
    const id = setInterval(load, 8000);
    return () => {
      cancelled = true;
      clearInterval(id);
      networkRef.current?.destroy();
    };
  }, [focusEntities]);

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <h1 className="text-2xl font-bold">{focusEntities ? "Fraud Cluster Graph" : "REC Ownership Network"}</h1>
        <span className="text-xs text-slate-500">
          {stats.nodes} entities &middot; {stats.edges} transfers
        </span>
      </div>
      <p className="text-slate-400 text-sm mb-4">
        Red nodes are part of a high-degree hub or an ownership cycle. Rebuilt live from the transfer graph every
        few seconds.
      </p>
      {focusEntities && (
        <button
          onClick={onClearFocus}
          className="mb-3 text-xs text-emerald-400 hover:underline bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5"
        >
          &larr; Show full network
        </button>
      )}
      <div ref={containerRef} className="h-[520px] bg-slate-900 border border-slate-800 rounded-xl" />
    </div>
  );
}
