import React from "react";

const ICON = { ISSUE: "⚙", TRANSFER: "⇄", RETIRE: "✓", REVOKE: "✕" };
const COLOR = {
  ISSUE: "bg-emerald-900/40 text-emerald-400",
  TRANSFER: "bg-amber-900/40 text-amber-400",
  RETIRE: "bg-slate-800 text-slate-300",
  REVOKE: "bg-red-900/40 text-red-400",
};

export default function BlockchainTimeline({ lifecycle }) {
  if (!lifecycle?.length) {
    return <div className="text-slate-500 text-sm">No on-chain lifecycle events yet.</div>;
  }

  return (
    <div className="space-y-0">
      {lifecycle.map((tx, i) => (
        <div key={tx.transaction_id} className="flex gap-3">
          <div className="flex flex-col items-center">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm ${COLOR[tx.transaction_type]}`}>
              {ICON[tx.transaction_type] || "?"}
            </div>
            {i < lifecycle.length - 1 && <div className="w-px flex-1 bg-slate-800 my-1" />}
          </div>
          <div className="pb-6">
            <div className="text-sm font-medium">{tx.transaction_type}</div>
            <div className="text-xs text-slate-400">
              {tx.sender || "—"} &rarr; {tx.receiver || "—"} &middot; qty {tx.quantity}
            </div>
            <div className="text-[11px] text-slate-500 font-mono">
              {new Date(tx.transaction_timestamp * 1000).toLocaleString()}
            </div>
            {tx.blockchain_tx_hash ? (
              <div className="text-[11px] text-slate-500 font-mono truncate max-w-xs">tx: {tx.blockchain_tx_hash}</div>
            ) : (
              <div className="text-[11px] text-amber-500">blockchain sync pending</div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
