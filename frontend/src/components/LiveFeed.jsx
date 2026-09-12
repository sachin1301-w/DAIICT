import React from "react";

const DECISION_TONE = {
  LEGITIMATE: "bg-emerald-900/40 text-emerald-400",
  SUSPICIOUS: "bg-amber-900/40 text-amber-400",
  FRAUD_SUSPECTED: "bg-red-900/40 text-red-400",
  CRITICAL: "bg-red-900/60 text-red-300",
};

function normalize(item) {
  if (item.rec) {
    return {
      recId: item.rec.rec_id,
      generator: item.rec.generator_id,
      quantity: item.rec.quantity,
      status: item.rec.status,
      blockchainHash: item.rec.blockchain_tx_hash,
      time: item.generation?.generation_timestamp,
    };
  }
  if (item.transaction) {
    return {
      recId: item.transaction.rec_id,
      generator: item.transaction.transaction_type,
      quantity: item.transaction.quantity,
      status: item.transaction.transaction_type,
      blockchainHash: item.transaction.blockchain_tx_hash,
      time: item.transaction.transaction_timestamp,
    };
  }
  return { recId: "—", generator: item.skipped || "—", quantity: "—", status: "—", blockchainHash: null, time: null };
}

export default function LiveFeed({ feed }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
        <h3 className="text-xs uppercase tracking-wide text-slate-400">Live Transaction Feed</h3>
        <span className="text-[11px] text-slate-500">{feed.length} events</span>
      </div>
      <div className="max-h-[480px] overflow-y-auto overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead className="text-slate-500 uppercase text-[10px] sticky top-0 bg-slate-900">
            <tr className="border-b border-slate-800">
              <th className="text-left px-3 py-2">Time</th>
              <th className="text-left px-3 py-2">REC ID</th>
              <th className="text-left px-3 py-2">Generator</th>
              <th className="text-left px-3 py-2">Qty</th>
              <th className="text-left px-3 py-2">ML</th>
              <th className="text-left px-3 py-2">Graph</th>
              <th className="text-left px-3 py-2">Final Risk</th>
              <th className="text-left px-3 py-2">Status</th>
              <th className="text-left px-3 py-2">Blockchain Hash</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {feed.map((item, i) => {
              const n = normalize(item);
              const decision = item.decision;
              return (
                <tr key={i}>
                  <td className="px-3 py-2 text-slate-500 whitespace-nowrap">
                    {n.time ? new Date(n.time * 1000).toLocaleTimeString() : "—"}
                  </td>
                  <td className="px-3 py-2 font-mono">{n.recId}</td>
                  <td className="px-3 py-2 truncate max-w-[110px]">{n.generator}</td>
                  <td className="px-3 py-2">{typeof n.quantity === "number" ? n.quantity.toFixed(2) : n.quantity}</td>
                  <td className="px-3 py-2">{item.ml?.ml_score ?? "—"}</td>
                  <td className="px-3 py-2">{item.graph?.graph_score ?? "—"}</td>
                  <td className="px-3 py-2 font-semibold">{decision?.final_risk_score ?? "—"}</td>
                  <td className="px-3 py-2">
                    {decision ? (
                      <span className={`badge ${DECISION_TONE[decision.decision] || "bg-slate-800 text-slate-300"}`}>
                        {decision.decision}
                      </span>
                    ) : (
                      n.status
                    )}
                  </td>
                  <td className="px-3 py-2 font-mono text-slate-500 truncate max-w-[100px]">
                    {n.blockchainHash ? n.blockchainHash.slice(0, 10) + "..." : "pending"}
                  </td>
                </tr>
              );
            })}
            {feed.length === 0 && (
              <tr>
                <td colSpan={9} className="px-3 py-8 text-center text-slate-500">
                  Waiting for the simulator... make sure the backend + WebSocket are running.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
