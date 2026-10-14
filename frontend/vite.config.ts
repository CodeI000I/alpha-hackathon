import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// В dev-режиме запросы /api проксируются на Go backend.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8080",
    },
  },
});
