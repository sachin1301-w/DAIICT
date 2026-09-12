import React, { useEffect, useState } from "react";
import { api } from "../api.js";

// Preset options per spec -- a plain <select> instead of a free-range
// slider, so "15% Fraud" is an exact, unambiguous value sent to the backend.
const FRAUD_PRESETS = [0, 5, 10, 15, 20, 30, 50];
const TAMPER_PRESETS = [0, 5, 10, 20, 50];

export default function SimulationControls({ compact = false, resetEpoch = 0, onReset }) {
  const [status, setStatus] = useState(null);
  const [interval, setIntervalValue] = useState(5);
  const [fraudProb, setFraudProb] = useState(15);
  const [tamperEnabled, setTamperEnabled] = useState(false);
  const [tamperProb, setTamperProb] = useState(5);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [justReset, setJustReset] = useState(false);

  function refreshStatus() {
    return api
      .simulationStatus()
      .then((s) => {
        setStatus(s);
        setIntervalValue(s.interval_seconds);
        setFraudProb(Math.round(s.fraud_probability * 100));
        setTamperEnabled(!!s.tamper_enabled);
        setTamperProb(Math.round((s.tamper_probability ?? 0.05) * 100));
      })
      .catch(() => {});
  }

  useEffect(() => {
    refreshStatus();
    const id = setInterval(refreshStatus, 4000);
    return () => clearInterval(id);
  }, []);

  // Reflect a reset triggered from elsewhere (e.g. another open tab, or the
  // websocket "simulation_reset" broadcast bubbled up through App.jsx).
  useEffect(() => {
    if (resetEpoch > 0) refreshStatus();
  }, [resetEpoch]);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      // Always sends the currently-selected values, so Start Simulation
      // uses this fraud probability/interval from its very first tick --
      // no separate "Apply" step needed first.
      await api.simulationStart({
        interval_seconds: Number(interval), fraud_probability: fraudProb / 100,
        tamper_enabled: tamperEnabled, tamper_probability: tamperProb / 100,
      });
      await refreshStatus();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function stop() {
    setBusy(true);
    setError(null);
    try {
      await api.simulationStop();
      await refreshStatus();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function applyConfig() {
    setBusy(true);
    setError(null);
    try {
      await api.simulationConfig({
        interval_seconds: Number(interval), fraud_probability: fraudProb / 100,
        tamper_enabled: tamperEnabled, tamper_probability: tamperProb / 100,
      });
      await refreshStatus();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    if (!confirm("Reset Transactions? This stops the simulator and permanently clears all simulated RECs, transactions, fraud alerts and graph data. Generators, ML models, the deployed contract, and the Verification Portal's history/audit log are not affected.")) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.simulationReset();
      await refreshStatus();
      setJustReset(true);
      setTimeout(() => setJustReset(false), 4000);
      onReset?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const observedPct = status ? Math.round(status.observed_fraud_rate * 1000) / 10 : 0;

  return (
    <div className={`bg-slate-900 border border-slate-800 rounded-xl ${compact ? "p-4" : "p-5"}`}>
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <h3 className="text-xs uppercase tracking-wide text-slate-400">Simulation Controls</h3>
        <div className="flex items-center gap-2">
          <span className={`badge ${status?.running ? "bg-emerald-900/40 text-emerald-400" : "bg-slate-800 text-slate-400"}`}>
            {status?.running ? "RUNNING" : "STOPPED"}
          </span>
          {status?.simulation_run_id && (
            <span className="text-[10px] font-mono text-slate-600">{status.simulation_run_id}</span>
          )}
        </div>
      </div>

      {justReset && (
        <div className="mb-3 text-xs bg-emerald-950/40 border border-emerald-900 text-emerald-400 rounded-lg px-3 py-2">
          Simulation data reset. Click Start Simulation to begin a fresh run from zero.
        </div>
      )}
      {error && <div className="mb-3 text-xs bg-red-950/40 border border-red-900 text-red-400 rounded-lg px-3 py-2">{error}</div>}

      <div className={`grid ${compact ? "grid-cols-1 sm:grid-cols-3" : "grid-cols-1 sm:grid-cols-2"} gap-3 mb-4`}>
        <label className="block text-xs text-slate-400">
          Interval (seconds)
          <input
            type="number"
            min="1"
            value={interval}
            onChange={(e) => setIntervalValue(e.target.value)}
            className="mt-1 w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-sm"
          />
        </label>
        <label className="block text-xs text-slate-400">
          Fraud probability
          <select
            value={fraudProb}
            onChange={(e) => setFraudProb(Number(e.target.value))}
            className="mt-1 w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-sm"
          >
            {FRAUD_PRESETS.map((p) => (
              <option key={p} value={p}>
                {p}% Fraud
              </option>
            ))}
          </select>
        </label>
        {!compact && (
          <>
            <label className="flex items-center gap-2 text-xs text-slate-400">
              <input
                type="checkbox"
                checked={tamperEnabled}
                onChange={(e) => setTamperEnabled(e.target.checked)}
                className="accent-red-600"
              />
              Enable Tampering Simulation (demo/test only)
            </label>
            <label className="block text-xs text-slate-400">
              Tampering Probability
              <select
                value={tamperProb}
                onChange={(e) => setTamperProb(Number(e.target.value))}
                disabled={!tamperEnabled}
                className="mt-1 w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-sm disabled:opacity-40"
              >
                {TAMPER_PRESETS.map((p) => (
                  <option key={p} value={p}>
                    {p}%
                  </option>
                ))}
              </select>
            </label>
            <button onClick={applyConfig} disabled={busy} className="text-xs text-emerald-400 hover:underline disabled:opacity-40 text-left sm:col-span-2">
              Apply to running simulation (takes effect on the next tick, no restart needed)
            </button>
          </>
        )}
      </div>

      {!compact && tamperEnabled && (
        <div className="mb-4 text-[11px] bg-amber-950/30 border border-amber-900 text-amber-400 rounded-lg px-3 py-2">
          SYNTHETIC TAMPERING SIMULATION -- for demonstration only. The simulator will occasionally edit an
          already-issued REC's energy/quantity directly in SQLite (without touching its anchored hash), so Verify
          REC has something real to catch. Tampered: {status?.tamper_injected_count ?? 0}.
        </div>
      )}

      <div className="flex gap-2 mb-4">
        <button
          onClick={start}
          disabled={busy || status?.running}
          className="flex-1 bg-emerald-700 hover:bg-emerald-600 disabled:opacity-40 rounded-lg py-2 text-sm font-medium"
        >
          Start Simulation
        </button>
        <button
          onClick={stop}
          disabled={busy || !status?.running}
          className="flex-1 bg-slate-800 hover:bg-slate-700 disabled:opacity-40 rounded-lg py-2 text-sm font-medium"
        >
          Stop Simulation
        </button>
        <button
          onClick={reset}
          disabled={busy}
          className="flex-1 bg-red-900/60 hover:bg-red-900 disabled:opacity-40 rounded-lg py-2 text-sm font-medium text-red-200"
        >
          Reset Transactions
        </button>
      </div>

      <div className="text-[11px] text-slate-500 font-mono flex flex-wrap gap-x-4 gap-y-1">
        <span>Configured: {fraudProb}%</span>
        <span>Generated: {status?.generated_count ?? 0}</span>
        <span>Fraudulent: {status?.fraud_injected_count ?? 0}</span>
        <span>Observed rate: {observedPct}%</span>
        <span>Ticks: {status?.ticks ?? 0}</span>
      </div>
    </div>
  );
}
