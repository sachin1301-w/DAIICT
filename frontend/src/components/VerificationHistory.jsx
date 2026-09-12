import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import VerificationStatusBadge from "./VerificationStatusBadge.jsx";
import BlockchainStatusBadge from "./BlockchainStatusBadge.jsx";

const RESULTS = ["", "VALID", "SUSPICIOUS", "INVALID", "TAMPERED", "NOT_FOUND", "PENDING", "UNCONFIRMED"];
const BC_STATUSES = ["", "PASSED", "FAILED", "PENDING", "NOT_CONNECTED"];

function fmtTime(ts) {
  return ts ? new Date(ts * 1000).toLocaleString() : "—";
}

export default function VerificationHistory({ resetEpoch = 0 }) {
  const [rows, setRows] = useState([]);
  const [filters, setFilters] = useState({ rec_id: "", company: "", result: "", blockchain_status: "" });
  const [busy, setBusy] = useState(false);

  function load() {
    setBusy(true);
    api
      .verificationHistory(filters)
      .then(setRows)
      .catch(() => {})
      .finally(() => setBusy(false));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetEpoch]);

  return (
    <div>
      <h1 className="text-2xl font-bold mb-1">Verification History</h1>
      <p className="text-slate-400 text-sm mb-6">
        Every REC verification ever performed through the portal -- including failed and NOT_FOUND attempts. Not
        cleared by Reset Transactions; this is a permanent compliance trail.
      </p>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          load();
        }}
        className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-4 items-end"
      >
        <label className="block text-xs text-slate-400">
          REC ID
          <input
            value={filters.rec_id}
            onChange={(e) => setFilters({ ...filters, rec_id: e.target.value })}
            className="mt-1 w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-sm font-mono"
          />
        </label>
        <label className="block text-xs text-slate-400">
          Company
          <input
            value={filters.company}
            onChange={(e) => setFilters({ ...filters, company: e.target.value })}
            className="mt-1 w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-sm"
          />
        </label>
        <label className="block text-xs text-slate-400">
          Result
          <select
            value={filters.result}
            onChange={(e) => setFilters({ ...filters, result: e.target.value })}
            className="mt-1 w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-sm"
          >
            {RESULTS.map((r) => (
              <option key={r} value={r}>
                {r || "All"}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-xs text-slate-400">
          Blockchain Status
          <select
            value={filters.blockchain_status}
            onChange={(e) => setFilters({ ...filters, blockchain_status: e.target.value })}
            className="mt-1 w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-sm"
          >
            {BC_STATUSES.map((s) => (
              <option key={s} value={s}>
                {s || "All"}
              </option>
            ))}
          </select>
        </label>
        <button className="bg-emerald-700 hover:bg-emerald-600 rounded-lg py-2 text-sm font-medium">
          {busy ? "Loading..." : "Filter"}
        </button>
      </form>

      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-slate-400 uppercase text-[10px]">
            <tr className="border-b border-slate-800">
              <th className="text-left px-4 py-3">Verification ID</th>
              <th className="text-left px-4 py-3">REC ID</th>
              <th className="text-left px-4 py-3">Company</th>
              <th className="text-left px-4 py-3">Verifier</th>
              <th className="text-left px-4 py-3">Date</th>
              <th className="text-left px-4 py-3">Result</th>
              <th className="text-left px-4 py-3">Blockchain</th>
              <th className="text-left px-4 py-3">Hash</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {rows.map((r) => (
              <tr key={r.verification_id}>
                <td className="px-4 py-2.5 font-mono">{r.verification_id}</td>
                <td className="px-4 py-2.5 font-mono">{r.rec_id}</td>
                <td className="px-4 py-2.5">{r.verifier_company || "—"}</td>
                <td className="px-4 py-2.5">{r.verifier_user || "—"}</td>
                <td className="px-4 py-2.5 text-slate-500">{fmtTime(r.requested_at)}</td>
                <td className="px-4 py-2.5">
                  <VerificationStatusBadge result={r.result} />
                </td>
                <td className="px-4 py-2.5">
                  <BlockchainStatusBadge status={r.blockchain_status} />
                </td>
                <td className="px-4 py-2.5">
                  <span
                    className={`badge ${r.hash_status === "MATCHED" ? "bg-emerald-900/40 text-emerald-400" : "bg-red-900/40 text-red-400"}`}
                  >
                    {r.hash_status}
                  </span>
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-8 text-center text-slate-500">
                  No verification requests match these filters yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
