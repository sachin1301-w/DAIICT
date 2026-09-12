import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // bind on all interfaces (not just localhost) so a phone on the same
    // WiFi can reach this via the dev machine's LAN IP -- needed for the
    // Blockchain Verify page's QR code to actually work when scanned.
    host: true,
  },
});
