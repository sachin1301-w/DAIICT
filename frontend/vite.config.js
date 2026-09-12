import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// GitHub Pages serves a project repo at /<repo-name>/, not /, so every
// asset URL needs that prefix in a production build -- but the local dev
// server must stay at / (that's what every existing "open localhost:5173"
// instruction in this project assumes), so this only applies to `build`.
export default defineConfig(({ command }) => ({
  plugins: [react(), tailwindcss()],
  base: command === "build" ? "/DAIICT/" : "/",
  server: {
    port: 5173,
    // bind on all interfaces (not just localhost) so a phone on the same
    // WiFi can reach this via the dev machine's LAN IP -- needed for the
    // Blockchain Verify page's QR code to actually work when scanned.
    host: true,
  },
}));
