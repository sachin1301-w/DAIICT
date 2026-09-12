import React from "react";

const TONE = {
  neutral: "text-slate-100",
  good: "text-emerald-400",
  warn: "text-amber-400",
  bad: "text-red-400",
};

export default function RiskCard({ label, value, tone = "neutral" }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
      <div className={`text-2xl font-bold ${TONE[tone]}`}>{value}</div>
      <div className="text-xs text-slate-400 mt-1">{label}</div>
    </div>
  );
}
