import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev-server proxy keeps the frontend origin clean; in Docker the nginx
// (or the app itself) serves /api from the API container.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_URL ?? "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
