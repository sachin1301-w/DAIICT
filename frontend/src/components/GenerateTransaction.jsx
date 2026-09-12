import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import SimulationControls from "./SimulationControls.jsx";

export default function GenerateTransaction({ resetEpoch }) {
  const [generators, setGenerators] = useState([]);
  const [form, setForm] = useState({ generator_id: "", energy_generated_mwh: 40, weather_factor: 0.85, rec_quantity: "" });
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.generators().then(setGenerators);
  }, []);

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
        <SimulationControls resetEpoch={resetEpoch} />

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
