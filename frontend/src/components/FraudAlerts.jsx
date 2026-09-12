import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import BlockchainTimeline from "./BlockchainTimeline.jsx";

const LEVELS = ["ALL", "LOW", "MEDIUM", "HIGH", "CRITICAL"];

const LEVEL_TONE = {
  LOW: "bg-slate-800 text-slate-300",
  MEDIUM: "bg-amber-900/40 text-amber-400",
  HIGH: "bg-orange-900/40 text-orange-400",
  CRITICAL: "bg-red-900/40 text-red-400",
};

export default function FraudAlerts() {
  const [alerts, setAlerts] = useState([]);
  const [level, setLevel] = useState("ALL");
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);

  function load() {
    api.alerts(level === "ALL" ? undefined : level).then(setAlerts).catch(() => {});
  }

  useEffect(() => {
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [level]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    api.alert(selectedId).then(setDetail).catch(() => setDetail(null));
  }, [selectedId]);

  return (
    <div>
      <h1 className="text-2xl font-bold mb-1">Fraud Alerts</h1>
      <p className="text-slate-400 text-sm mb-4">
        Every transaction the fraud decision engine held for review (SUSPICIOUS, FRAUD_SUSPECTED or CRITICAL).
      </p>

      <div className="flex gap-2 mb-4">
        {LEVELS.map((lvl) => (
          <button
            key={lvl}
            onClick={() => setLevel(lvl)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium ${
              level === lvl ? "bg-emerald-700 text-white" : "bg-slate-900 border border-slate-800 text-slate-400"
            }`}
          >
            {lvl}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <div className={`bg-slate-900 border border-slate-800 rounded-xl overflow-x-auto ${detail ? "xl:col-span-2" : "xl:col-span-3"}`}>
          <table className="w-full text-xs">
            <thead className="text-slate-400 uppercase text-[10px]">
              <tr className="border-b border-slate-800">
                <th className="text-left px-4 py-3">Alert ID</th>
                <th className="text-left px-4 py-3">REC / Tx</th>
                <th className="text-left px-4 py-3">Fraud Type</th>
                <th className="text-left px-4 py-3">Rule</th>
                <th className="text-left px-4 py-3">ML</th>
                <th className="text-left px-4 py-3">Graph</th>
                <th className="text-left px-4 py-3">Final Risk</th>
                <th className="text-left px-4 py-3">Risk Level</th>
                <th className="text-left px-4 py-3">Status</th>
                <th className="text-left px-4 py-3">Time</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {alerts.map((a) => (
                <tr
                  key={a.alert_id}
                  onClick={() => setSelectedId(a.alert_id)}
                  className={`cursor-pointer hover:bg-slate-800/50 ${selectedId === a.alert_id ? "bg-slate-800/70" : ""}`}
                >
                  <td className="px-4 py-2.5 font-mono">{a.alert_id}</td>
                  <td className="px-4 py-2.5 font-mono">{a.rec_id || a.transaction_id || "—"}</td>
                  <td className="px-4 py-2.5">{a.fraud_type || "—"}</td>
                  <td className="px-4 py-2.5">{a.rule_score}</td>
                  <td className="px-4 py-2.5">{a.ml_score}</td>
                  <td className="px-4 py-2.5">{a.graph_score}</td>
                  <td className="px-4 py-2.5 font-semibold">{a.final_risk_score}</td>
                  <td className="px-4 py-2.5">
                    <span className={`badge ${LEVEL_TONE[a.risk_level] || ""}`}>{a.risk_level}</span>
                  </td>
                  <td className="px-4 py-2.5">{a.status}</td>
                  <td className="px-4 py-2.5 text-slate-500">
                    {new Date(a.created_at * 1000).toLocaleTimeString()}
                  </td>
                </tr>
              ))}
              {alerts.length === 0 && (
                <tr>
                  <td colSpan={10} className="px-4 py-8 text-center text-slate-500">
                    No alerts at this severity level.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {detail && (
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 text-xs">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-xs uppercase tracking-wide text-slate-400">{detail.alert_id}</h3>
              <button onClick={() => setSelectedId(null)} className="text-slate-500 hover:text-slate-300">
                close
              </button>
            </div>

            <div className="mb-3">
              <span className={`badge ${LEVEL_TONE[detail.risk_level] || ""}`}>{detail.risk_level}</span>{" "}
              <span className="text-slate-400">final risk {detail.final_risk_score}</span>
            </div>

            <div className="mb-4">
              <div className="text-slate-500 mb-1">Reasons</div>
              <ul className="list-disc list-inside space-y-0.5 text-slate-300">
                {detail.reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </div>

            {detail.rec && (
              <div className="mb-4">
                <div className="text-slate-500 mb-1">Certificate</div>
                <div className="font-mono">{detail.rec.rec_id}</div>
                <div className="text-slate-400">
                  {detail.rec.quantity} qty &middot; status {detail.rec.status}
                </div>
              </div>
            )}

            {detail.related_entities?.length > 0 && (
              <div className="mb-4">
                <div className="text-slate-500 mb-1">Related Entities</div>
                <ul className="space-y-0.5">
                  {detail.related_entities.map((e) => (
                    <li key={e} className="font-mono truncate">
                      {e}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {detail.lifecycle?.length > 0 && (
              <div>
                <div className="text-slate-500 mb-2">Blockchain History</div>
                <BlockchainTimeline lifecycle={detail.lifecycle} />
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
