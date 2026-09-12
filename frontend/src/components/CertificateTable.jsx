import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import BlockchainStatusBadge from "./BlockchainStatusBadge.jsx";

const STATUS_TONE = {
  ACTIVE: "bg-emerald-900/40 text-emerald-400",
  RETIRED: "bg-slate-800 text-slate-300",
  REVOKED: "bg-red-900/40 text-red-400",
  HELD: "bg-amber-900/40 text-amber-400",
};

export default function CertificateTable({ resetEpoch = 0 }) {
  const [certs, setCerts] = useState([]);
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(null);

  function load() {
    api.certificates(filter || undefined).then(setCerts).catch(() => {});
  }

  useEffect(load, [filter, resetEpoch]);

  async function retire(recId) {
    setBusy(recId);
    try {
      await api.retireCertificate(recId);
      load();
    } catch (e) {
      alert(e.message);
    } finally {
      setBusy(null);
    }
  }

  async function revoke(recId) {
    const reason = prompt("Reason for revoking this REC?", "confirmed fraud");
    if (reason === null) return;
    setBusy(recId);
    try {
      await api.revokeCertificate(recId, reason);
      load();
    } catch (e) {
      alert(e.message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold">REC Lifecycle</h1>
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-sm"
        >
          <option value="">All statuses</option>
          <option value="ACTIVE">Active</option>
          <option value="HELD">Held</option>
          <option value="RETIRED">Retired</option>
          <option value="REVOKED">Revoked</option>
        </select>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-slate-400 uppercase text-[10px]">
            <tr className="border-b border-slate-800">
              <th className="text-left px-4 py-3">REC ID</th>
              <th className="text-left px-4 py-3">Generator</th>
              <th className="text-left px-4 py-3">Quantity</th>
              <th className="text-left px-4 py-3">Owner</th>
              <th className="text-left px-4 py-3">Status</th>
              <th className="text-left px-4 py-3">Blockchain</th>
              <th className="text-left px-4 py-3">Blockchain Tx</th>
              <th className="text-left px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {certs.map((c) => (
              <tr key={c.rec_id}>
                <td className="px-4 py-2.5 font-mono">{c.rec_id}</td>
                <td className="px-4 py-2.5">{c.generator_id}</td>
                <td className="px-4 py-2.5">{c.quantity?.toFixed(2)}</td>
                <td className="px-4 py-2.5 font-mono truncate max-w-[140px]">{c.current_owner}</td>
                <td className="px-4 py-2.5">
                  <span className={`badge ${STATUS_TONE[c.status] || ""}`}>{c.status}</span>
                </td>
                <td className="px-4 py-2.5">
                  <BlockchainStatusBadge status={c.blockchain_status} title={c.blockchain_verification_message} />
                </td>
                <td className="px-4 py-2.5 font-mono truncate max-w-[120px]">
                  {c.blockchain_tx_hash ? c.blockchain_tx_hash.slice(0, 12) + "..." : "pending sync"}
                </td>
                <td className="px-4 py-2.5 space-x-2">
                  {c.status === "ACTIVE" && (
                    <>
                      <button
                        disabled={busy === c.rec_id}
                        onClick={() => retire(c.rec_id)}
                        className="text-emerald-400 hover:underline disabled:opacity-40"
                      >
                        Retire
                      </button>
                      <button
                        disabled={busy === c.rec_id}
                        onClick={() => revoke(c.rec_id)}
                        className="text-red-400 hover:underline disabled:opacity-40"
                      >
                        Revoke
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
            {certs.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-8 text-center text-slate-500">
                  No certificates yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
