import React from "react";

// Text label always accompanies the color -- never color alone.
const TONE = {
  VALID: "bg-emerald-900/40 text-emerald-400",
  SUSPICIOUS: "bg-amber-900/40 text-amber-400",
  INVALID: "bg-orange-900/40 text-orange-400",
  TAMPERED: "bg-red-900/50 text-red-300",
  NOT_FOUND: "bg-slate-700/50 text-slate-400",
  PENDING: "bg-amber-900/40 text-amber-400",
  UNCONFIRMED: "bg-slate-700/50 text-slate-400",
};

export default function VerificationStatusBadge({ result, size = "normal" }) {
  const r = result || "PENDING";
  const sizeClass = size === "large" ? "text-sm px-3 py-1" : "";
  return <span className={`badge ${sizeClass} ${TONE[r] || TONE.PENDING}`}>{r.replace("_", " ")}</span>;
}
