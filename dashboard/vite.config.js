import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: proxy /api/* straight through to the backend (which serves /api/v1/*).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://localhost:8000", changeOrigin: true } },
  },
});
