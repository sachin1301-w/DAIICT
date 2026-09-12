import React, { useEffect, useState } from "react";
import { api } from "../api.js";

export default function FraudClusters({ onOpenGraph }) {
  const [clusters, setClusters] = useState([]);

  useEffect(() => {
    const load = () => api.fraudClusters().then(setClusters).catch(() => {});
    load();
    const id = setInterval(load, 6000);
    return () => clearInterval(id);
  }, []);

  return (
    <div>
      <h1 className="text-2xl font-bold mb-1">Fraud Cluster Detection</h1>
      <p className="text-slate-400 text-sm mb-6">
        Graph-based detection over the live REC ownership/transfer graph -- circular ownership, dense clusters,
        rapid transfer chains, repeated counterparties and high-degree hubs.
      </p>

      {clusters.length === 0 && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 text-center text-slate-500 text-sm">
          No suspicious clusters detected right now.
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
        {clusters.map((c) => (
          <div
            key={c.cluster_id}
            onClick={() => onOpenGraph?.(c.entity_ids)}
            className="bg-slate-900 border border-red-900/60 rounded-xl p-5 cursor-pointer hover:border-red-600 transition"
            title="Click to view this cluster's network graph"
          >
            <div className="text-xs text-slate-400 font-mono mb-1">{c.cluster_id}</div>
            <div className="text-3xl font-bold text-red-400 mb-3">{c.graph_score}%</div>
            <div className="grid grid-cols-3 gap-2 text-center text-xs text-slate-400 mb-3">
              <div>
                <div className="text-slate-100 font-semibold">{c.entities_involved}</div>
                Entities
              </div>
              <div>
                <div className="text-slate-100 font-semibold">{c.recs_involved}</div>
                RECs
              </div>
              <div>
                <div className="text-slate-100 font-semibold">{c.transfers_involved}</div>
                Transfers
              </div>
            </div>
            <ul className="text-xs text-slate-400 space-y-1 mb-3 list-disc list-inside">
              {c.patterns.map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ul>
            <div className="text-[11px] text-slate-500 border-t border-slate-800 pt-2 truncate">
              {c.entity_ids.join(", ")}
            </div>
            <div className="text-[11px] text-emerald-400 mt-2">View network graph &rarr;</div>
          </div>
        ))}
      </div>
    </div>
  );
}
