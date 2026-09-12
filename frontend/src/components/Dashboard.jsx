import React, { useEffect, useState } from "react";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from "recharts";
import RiskCard from "./RiskCard.jsx";
import LiveFeed from "./LiveFeed.jsx";
import SimulationControls from "./SimulationControls.jsx";
import BlockchainStatusBadge from "./BlockchainStatusBadge.jsx";
import VerificationStatusBadge from "./VerificationStatusBadge.jsx";
import { api } from "../api.js";

const COLORS = ["#34d399", "#fbbf24", "#f87171", "#94a3b8"];

export default function Dashboard({ feed, resetEpoch = 0 }) {
  const [summary, setSummary] = useState(null);

  useEffect(() => {
    const load = () => api.dashboardSummary().then(setSummary).catch(() => {});
    load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, [resetEpoch]);

  if (!summary) {
    return <div className="text-slate-400 text-sm">Loading dashboard...</div>;
  }

  const recStatusData = [
    { name: "Active", value: summary.active_recs },
    { name: "Retired", value: summary.retired_recs },
    { name: "Other", value: Math.max(summary.total_recs_issued - summary.active_recs - summary.retired_recs, 0) },
  ].filter((d) => d.value > 0);

  return (
    <div>
      <h1 className="text-2xl font-bold mb-1">System Overview</h1>
      <p className="text-slate-400 text-sm mb-6">
        Continuous simulation: {summary.simulation.running ? "running" : "stopped"} &middot; tick interval{" "}
        {summary.simulation.interval_seconds}s &middot; fraud probability{" "}
        {(summary.simulation.fraud_probability * 100).toFixed(0)}%
      </p>

      <div className="mb-6">
        <SimulationControls compact resetEpoch={resetEpoch} />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <RiskCard label="Total Generators" value={summary.total_generators} />
        <RiskCard label="Total RECs Issued" value={summary.total_recs_issued} />
        <RiskCard label="Active RECs" value={summary.active_recs} tone="good" />
        <RiskCard label="Retired RECs" value={summary.retired_recs} />
        <RiskCard label="Total Transactions" value={summary.total_transactions} />
        <RiskCard label="Suspicious Transactions" value={summary.suspicious_transactions} tone="warn" />
        <RiskCard label="Fraud Alerts (open)" value={`${summary.open_fraud_alerts}/${summary.fraud_alerts}`} tone="bad" />
        <RiskCard label="Average Risk Score" value={summary.average_risk_score} tone="warn" />
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 mb-6">
        <h3 className="text-xs uppercase tracking-wide text-slate-400 mb-3">Blockchain Verification</h3>
        <div className="flex flex-wrap gap-3">
          <div className="flex items-center gap-2">
            <BlockchainStatusBadge status="PASSED" />
            <span className="text-lg font-bold">{summary.blockchain_verification.passed}</span>
          </div>
          <div className="flex items-center gap-2">
            <BlockchainStatusBadge status="FAILED" />
            <span className="text-lg font-bold">{summary.blockchain_verification.failed}</span>
          </div>
          <div className="flex items-center gap-2">
            <BlockchainStatusBadge status="PENDING" />
            <span className="text-lg font-bold">{summary.blockchain_verification.pending}</span>
          </div>
          <div className="flex items-center gap-2">
            <BlockchainStatusBadge status="NOT_CONNECTED" />
            <span className="text-lg font-bold">{summary.blockchain_verification.not_connected}</span>
          </div>
          <div className="ml-auto text-xs text-slate-500 self-center">
            Hardhat node: {summary.blockchain.status}
          </div>
        </div>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 mb-6">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs uppercase tracking-wide text-slate-400">Verification Summary</h3>
          <span className="text-[11px] text-slate-600">
            {summary.verification_summary.total} total &middot; not affected by Reset Transactions
          </span>
        </div>
        <div className="flex flex-wrap gap-3">
          <div className="flex items-center gap-2">
            <VerificationStatusBadge result="VALID" />
            <span className="text-lg font-bold">{summary.verification_summary.valid}</span>
          </div>
          <div className="flex items-center gap-2">
            <VerificationStatusBadge result="SUSPICIOUS" />
            <span className="text-lg font-bold">{summary.verification_summary.suspicious}</span>
          </div>
          <div className="flex items-center gap-2">
            <VerificationStatusBadge result="TAMPERED" />
            <span className="text-lg font-bold">{summary.verification_summary.tampered}</span>
          </div>
          <div className="flex items-center gap-2">
            <VerificationStatusBadge result="NOT_FOUND" />
            <span className="text-lg font-bold">{summary.verification_summary.not_found}</span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <LiveFeed feed={feed} />
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <h3 className="text-xs uppercase tracking-wide text-slate-400 mb-2">REC Status Breakdown</h3>
          <ResponsiveContainer width="100%" height={220}>
            <PieChart>
              <Pie data={recStatusData} dataKey="value" nameKey="name" innerRadius={45} outerRadius={80}>
                {recStatusData.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #1e293b" }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
