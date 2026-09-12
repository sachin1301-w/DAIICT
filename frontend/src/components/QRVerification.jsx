import React, { useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { api } from "../api.js";
import BlockchainTimeline from "./BlockchainTimeline.jsx";

function verifyUrlFor(recId) {
  return `${window.location.origin}${window.location.pathname}?verify=${encodeURIComponent(recId)}`;
}

export default function QRVerification({ initialRecId = "" }) {
  const [recId, setRecId] = useState(initialRecId);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function runLookup(id) {
    const target = id.trim();
    if (!target) return;
    setBusy(true);
    setError(null);
    setData(null);
    try {
      const result = await api.verifyRec(target);
      setData(result);
      // Keep the URL in sync with what was actually looked up, so the QR
      // code (and the address bar itself) always reflects a working,
      // shareable deep link -- refreshing or re-scanning re-runs this same check.
      window.history.replaceState(null, "", verifyUrlFor(target));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  // auto-run when opened via a QR code / shared "?verify=" link
  useEffect(() => {
    if (initialRecId) runLookup(initialRecId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const tampered = data?.hash_verification && data.hash_verification.tampered;
  const qrValue = recId.trim() ? verifyUrlFor(recId.trim()) : null;
  const isLanHost = /^(localhost|127\.0\.0\.1)$/.test(window.location.hostname);

  return (
    <div>
      <h1 className="text-2xl font-bold mb-1">Blockchain Verification</h1>
      <p className="text-slate-400 text-sm mb-6">
        Look up a REC by ID to see its on-chain status, generation-data hash integrity, and full lifecycle. The QR
        code encodes a real link back to this page with the same REC pre-loaded -- scanning it with a phone camera
        opens the verification result directly, not just the ID as plain text.
      </p>

      {isLanHost && (
        <div className="mb-6 max-w-2xl text-xs bg-amber-950/30 border border-amber-900 text-amber-300 rounded-lg p-3">
          You're viewing this via <code>localhost</code>, which a phone can't reach. To make the QR code scannable,
          open this dashboard from <code>http://{window.location.hostname === "localhost" ? "<your-PC's-LAN-IP>" : window.location.hostname}:5173</code>{" "}
          on this PC instead (same WiFi as your phone) -- then the QR will encode a link your phone can actually open.
        </div>
      )}

      <form onSubmit={(e) => { e.preventDefault(); runLookup(recId); }} className="flex gap-2 mb-6 max-w-md">
        <input
          value={recId}
          onChange={(e) => setRecId(e.target.value)}
          placeholder="e.g. REC-a1b2c3d4e5"
          className="flex-1 bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-sm font-mono"
        />
        <button
          disabled={busy || !recId.trim()}
          className="bg-emerald-700 hover:bg-emerald-600 disabled:opacity-50 rounded-lg px-4 py-2 text-sm font-medium"
        >
          Verify
        </button>
      </form>

      {error && <div className="text-red-400 text-sm mb-4">{error}</div>}

      {data && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 flex flex-col items-center gap-3">
            <QRCodeSVG value={qrValue || data.rec.rec_id} size={140} bgColor="#0f172a" fgColor="#e2e8f0" />
            <div className="text-xs font-mono text-slate-400">{data.rec.rec_id}</div>
            <div className="text-[10px] text-slate-600 text-center break-all">{qrValue}</div>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 lg:col-span-2">
            <h3 className="text-xs uppercase tracking-wide text-slate-400 mb-3">Certificate Details</h3>
            <dl className="grid grid-cols-2 gap-y-2 text-xs">
              <dt className="text-slate-500">Generator</dt>
              <dd>{data.rec.generator_id}</dd>
              <dt className="text-slate-500">Quantity</dt>
              <dd>{data.rec.quantity}</dd>
              <dt className="text-slate-500">Status</dt>
              <dd>{data.rec.status}</dd>
              <dt className="text-slate-500">Current Owner</dt>
              <dd className="font-mono truncate">{data.rec.current_owner}</dd>
              <dt className="text-slate-500">On-chain Status</dt>
              <dd>{data.onchain ? data.onchain.status : "not synced to blockchain"}</dd>
            </dl>

            <div
              className={`mt-4 rounded-lg p-3 text-xs ${
                tampered ? "bg-red-950/60 text-red-300 border border-red-800" : "bg-emerald-950/40 text-emerald-400 border border-emerald-900"
              }`}
            >
              {data.hash_verification
                ? tampered
                  ? "DATA INTEGRITY FAILURE -- the current generation record does not match its anchored hash."
                  : "Data integrity verified: recomputed hash matches the stored/anchored hash."
                : "No generation record to verify."}
            </div>

            <h3 className="text-xs uppercase tracking-wide text-slate-400 mt-5 mb-3">Lifecycle</h3>
            <BlockchainTimeline lifecycle={data.lifecycle} />
          </div>
        </div>
      )}
    </div>
  );
}
