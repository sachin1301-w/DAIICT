// Derive from the page's own hostname rather than hardcoding "localhost":
// when this page is opened from a phone via the dev machine's LAN IP
// (e.g. scanning the QR code on the Blockchain Verify page), "localhost"
// would resolve to the phone itself, not the dev machine.
const BASE = import.meta.env.VITE_API_BASE || `http://${window.location.hostname}:8000`;

async function request(path, options) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const isJson = res.headers.get("content-type")?.includes("application/json");
  const body = isJson ? await res.json() : await res.text();
  if (!res.ok) {
    const message = typeof body === "object" ? body.detail || JSON.stringify(body) : body;
    throw new Error(message);
  }
  return body;
}

export const api = {
  health: () => request("/api/health"),
  dashboardSummary: () => request("/api/dashboard/summary"),

  generators: () => request("/api/generators"),
  createGenerator: (payload) => request("/api/generators", { method: "POST", body: JSON.stringify(payload) }),

  transactions: (limit = 100) => request(`/api/transactions?limit=${limit}`),
  certificates: (status) => request(`/api/certificates${status ? `?status=${status}` : ""}`),
  retireCertificate: (recId) => request(`/api/certificates/${recId}/retire`, { method: "POST", body: "{}" }),
  revokeCertificate: (recId, reason) =>
    request(`/api/certificates/${recId}/revoke`, { method: "POST", body: JSON.stringify({ reason }) }),

  alerts: (riskLevel) => request(`/api/alerts${riskLevel ? `?risk_level=${riskLevel}` : ""}`),
  alert: (alertId) => request(`/api/alerts/${alertId}`),

  fraudClusters: () => request("/api/fraud-clusters"),
  networkGraph: () => request("/api/network-graph"),

  blockchainStatus: () => request("/api/blockchain/status"),
  verifyRec: (recId) => request(`/api/verify/${recId}`),

  simulationStart: () => request("/api/simulation/start", { method: "POST" }),
  simulationStop: () => request("/api/simulation/stop", { method: "POST" }),
  simulationStatus: () => request("/api/simulation/status"),
  simulationConfig: (payload) => request("/api/simulation/config", { method: "POST", body: JSON.stringify(payload) }),

  submitGeneration: (payload) => request("/api/generation", { method: "POST", body: JSON.stringify(payload) }),
  submitTransfer: (payload) => request("/api/transactions/transfer", { method: "POST", body: JSON.stringify(payload) }),
};

export function connectLiveFeed(onMessage) {
  const wsBase = BASE.replace(/^http/, "ws");
  let ws;
  let closedByClient = false;

  function connect() {
    ws = new WebSocket(`${wsBase}/ws`);
    ws.onmessage = (event) => {
      try {
        onMessage(JSON.parse(event.data));
      } catch {
        /* ignore malformed frame */
      }
    };
    ws.onclose = () => {
      if (!closedByClient) setTimeout(connect, 2000);
    };
  }
  connect();

  return () => {
    closedByClient = true;
    ws?.close();
  };
}
