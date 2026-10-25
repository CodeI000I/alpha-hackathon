import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// В dev-режиме запросы /api проксируются на Go backend.
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      input: {
        app: new URL("./index.html", import.meta.url).pathname,
        bank: new URL("./bank.html", import.meta.url).pathname,
        reportCharts: new URL("./report-charts.html", import.meta.url).pathname,
      },
    },
  },
  server: {
    proxy: {
      "/api": "http://localhost:8080",
    },
  },
});
