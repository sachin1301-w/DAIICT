import React, { useEffect, useState } from "react";
import { api } from "../api.js";

export default function GenerateTransaction() {
  const [status, setStatus] = useState(null);
  const [interval, setIntervalValue] = useState(5);
  const [fraudProb, setFraudProb] = useState(15);
  const [generators, setGenerators] = useState([]);
  const [form, setForm] = useState({ generator_id: "", energy_generated_mwh: 40, weather_factor: 0.85, rec_quantity: "" });
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  function refreshStatus() {
    api.simulationStatus().then((s) => {
      setStatus(s);
      setIntervalValue(s.interval_seconds);
      setFraudProb(Math.round(s.fraud_probability * 100));
    });
  }

  useEffect(() => {
    refreshStatus();
    api.generators().then(setGenerators);
    const id = setInterval(refreshStatus, 4000);
    return () => clearInterval(id);
  }, []);

  async function applyConfig() {
    await api.simulationConfig({ interval_seconds: Number(interval), fraud_probability: fraudProb / 100 });
    refreshStatus();
  }

  async function submitGeneration(e) {
    e.preventDefault();
    setBusy(true);
    setResult(null);
    try {
      const payload = {
        generator_id: form.generator_id,
        energy_generated_mwh: Number(form.energy_generated_mwh),
        weather_factor: Number(form.weather_factor),
      };
      if (form.rec_quantity !== "") payload.rec_quantity = Number(form.rec_quantity);
      const res = await api.submitGeneration(payload);
      setResult(res);
    } catch (err) {
      setResult({ error: err.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-1">Simulation Control</h1>
      <p className="text-slate-400 text-sm mb-6">
        The background simulator continuously generates realistic (and occasionally fraudulent) REC activity. You
        can also manually submit one generation reading through the full pipeline below.
      </p>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h3 className="text-xs uppercase tracking-wide text-slate-400 mb-4">Background Simulator</h3>
          <div className="flex items-center gap-3 mb-4">
            <span className={`badge ${status?.running ? "bg-emerald-900/40 text-emerald-400" : "bg-slate-800 text-slate-400"}`}>
              {status?.running ? "RUNNING" : "STOPPED"}
            </span>
            <span className="text-xs text-slate-500">{status?.ticks ?? 0} ticks so far</span>
          </div>

          <div className="space-y-3 mb-4">
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
              Fraud probability: {fraudProb}%
              <input
                type="range"
                min="0"
                max="60"
                value={fraudProb}
                onChange={(e) => setFraudProb(Number(e.target.value))}
                className="mt-1 w-full"
              />
            </label>
            <button onClick={applyConfig} className="text-xs text-emerald-400 hover:underline">
              Apply config
            </button>
          </div>

          <div className="flex gap-2">
            <button
              onClick={() => api.simulationStart().then(refreshStatus)}
              className="flex-1 bg-emerald-700 hover:bg-emerald-600 rounded-lg py-2 text-sm font-medium"
            >
              Start
            </button>
            <button
              onClick={() => api.simulationStop().then(refreshStatus)}
              className="flex-1 bg-slate-800 hover:bg-slate-700 rounded-lg py-2 text-sm font-medium"
            >
              Stop
            </button>
          </div>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h3 className="text-xs uppercase tracking-wide text-slate-400 mb-4">Submit a Generation Reading</h3>
          <form onSubmit={submitGeneration} className="space-y-3">
            <label className="block text-xs text-slate-400">
              Generator
              <select
                required
                value={form.generator_id}
                onChange={(e) => setForm({ ...form, generator_id: e.target.value })}
                className="mt-1 w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-sm"
              >
                <option value="">Select...</option>
                {generators.map((g) => (
                  <option key={g.generator_id} value={g.generator_id}>
                    {g.name} ({g.capacity_mw} MW {g.plant_type})
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-xs text-slate-400">
              Energy Generated (MWh)
              <input
                type="number"
                step="any"
                required
                value={form.energy_generated_mwh}
                onChange={(e) => setForm({ ...form, energy_generated_mwh: e.target.value })}
                className="mt-1 w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-sm"
              />
            </label>
            <label className="block text-xs text-slate-400">
              REC Quantity (optional -- defaults to energy generated)
              <input
                type="number"
                step="any"
                value={form.rec_quantity}
                onChange={(e) => setForm({ ...form, rec_quantity: e.target.value })}
                placeholder="try a much larger number to test over-issuance"
                className="mt-1 w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-sm"
              />
            </label>
            <button
              disabled={busy}
              className="w-full bg-emerald-700 hover:bg-emerald-600 disabled:opacity-50 rounded-lg py-2 text-sm font-medium"
            >
              {busy ? "Running pipeline..." : "Run Pipeline"}
            </button>
          </form>

          {result && (
            <div className="mt-4 text-xs bg-slate-950 border border-slate-800 rounded-lg p-3">
              {result.error ? (
                <div className="text-red-400">{result.error}</div>
              ) : (
                <>
                  <div className="mb-1">
                    Decision:{" "}
                    <span className="font-semibold">{result.decision.decision}</span> (risk{" "}
                    {result.decision.final_risk_score})
                  </div>
                  <ul className="list-disc list-inside text-slate-400 space-y-0.5">
                    {result.decision.reasons.slice(0, 5).map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                  {result.ml?.legacy?.available && (
                    <div className="mt-2 pt-2 border-t border-slate-800 text-slate-500">
                      Legacy REC-issuance models (isolation_forest_model.pkl + xgboost_risk_model.pkl): anomaly{" "}
                      {result.ml.legacy.anomaly_score}, risk {result.ml.legacy.risk_score}%
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
