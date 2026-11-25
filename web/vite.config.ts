import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Dev: `npm run dev` proxies /api to the Python backend on :8765.
// Build: output goes into the Python package so `folio-desk serve` serves it.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
  build: { outDir: "../folio_desk/static", emptyOutDir: true },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test-setup.ts"] },
});
