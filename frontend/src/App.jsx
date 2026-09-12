import React, { useEffect, useState } from "react";
import Dashboard from "./components/Dashboard.jsx";
import CertificateTable from "./components/CertificateTable.jsx";
import FraudAlerts from "./components/FraudAlerts.jsx";
import FraudClusters from "./components/FraudClusters.jsx";
import NetworkGraph from "./components/NetworkGraph.jsx";
import GenerateTransaction from "./components/GenerateTransaction.jsx";
import QRVerification from "./components/QRVerification.jsx";
import { api, connectLiveFeed } from "./api.js";

const NAV = [
  { id: "dashboard", label: "Dashboard" },
  { id: "certificates", label: "Certificates" },
  { id: "alerts", label: "Fraud Alerts" },
  { id: "clusters", label: "Fraud Clusters" },
  { id: "graph", label: "Network Graph" },
  { id: "simulation", label: "Simulation Control" },
  { id: "verify", label: "Blockchain Verify" },
];

function initialViewFromUrl() {
  const recId = new URLSearchParams(window.location.search).get("verify");
  return recId ? "verify" : "dashboard";
}

function initialRecIdFromUrl() {
  return new URLSearchParams(window.location.search).get("verify") || "";
}

export default function App() {
  const [view, setView] = useState(initialViewFromUrl);
  const [feed, setFeed] = useState([]);
  const [chainStatus, setChainStatus] = useState(null);
  const [graphFocus, setGraphFocus] = useState(null);

  function openClusterGraph(entityIds) {
    setGraphFocus(entityIds);
    setView("graph");
  }

  useEffect(() => {
    const disconnect = connectLiveFeed((msg) => {
      if (msg.type === "pipeline_result") {
        setFeed((prev) => [msg.data, ...prev].slice(0, 60));
      }
    });
    return disconnect;
  }, []);

  useEffect(() => {
    const poll = () => api.blockchainStatus().then(setChainStatus).catch(() => setChainStatus({ status: "OFFLINE" }));
    poll();
    const id = setInterval(poll, 10000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="min-h-screen flex bg-slate-950">
      <aside className="w-60 shrink-0 border-r border-slate-800 flex flex-col p-4 gap-1">
        <div className="flex items-center gap-2 pb-4 mb-3 border-b border-slate-800">
          <span className="text-2xl">&#9889;</span>
          <div>
            <div className="font-bold text-sm">REC Guard</div>
            <div className="text-[11px] text-slate-400">Blockchain + AI Fraud Platform</div>
          </div>
        </div>
        {NAV.map((n) => (
          <button
            key={n.id}
            onClick={() => setView(n.id)}
            className={`text-left px-3 py-2 rounded-lg text-sm transition ${
              view === n.id ? "bg-emerald-700 text-white" : "text-slate-400 hover:bg-slate-900 hover:text-slate-100"
            }`}
          >
            {n.label}
          </button>
        ))}
        <div className="mt-auto pt-3 border-t border-slate-800 text-[11px]">
          <div
            className={`rounded-full px-3 py-1.5 text-center ${
              chainStatus?.status === "ONLINE" ? "bg-emerald-900/40 text-emerald-400" : "bg-red-900/40 text-red-400"
            }`}
          >
            Blockchain {chainStatus?.status || "checking..."}
          </div>
        </div>
      </aside>

      <main className="flex-1 p-8 overflow-y-auto max-h-screen">
        {view === "dashboard" && <Dashboard feed={feed} />}
        {view === "certificates" && <CertificateTable />}
        {view === "alerts" && <FraudAlerts />}
        {view === "clusters" && <FraudClusters onOpenGraph={openClusterGraph} />}
        {view === "graph" && <NetworkGraph focusEntities={graphFocus} onClearFocus={() => setGraphFocus(null)} />}
        {view === "simulation" && <GenerateTransaction />}
        {view === "verify" && <QRVerification initialRecId={initialRecIdFromUrl()} />}
      </main>
    </div>
  );
}
