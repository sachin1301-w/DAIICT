import React from "react";

// Text label always accompanies the color (never color alone), per
// accessibility requirement -- these read fine without color vision too.
const TONE = {
  PASSED: "bg-emerald-900/40 text-emerald-400",
  FAILED: "bg-red-900/40 text-red-400",
  PENDING: "bg-amber-900/40 text-amber-400",
  NOT_CONNECTED: "bg-slate-700/50 text-slate-400",
};

export default function BlockchainStatusBadge({ status, title }) {
  const s = status || "PENDING";
  return (
    <span className={`badge ${TONE[s] || TONE.PENDING}`} title={title}>
      {s.replace("_", " ")}
    </span>
  );
}
