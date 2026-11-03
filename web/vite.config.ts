import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: run `mvm serve` (port 8765) for /data (export bundle + audio with HTTP Range), then `npm run dev`.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    proxy: { "/data": "http://127.0.0.1:8765", "/api": "http://127.0.0.1:8765" },
  },
});
