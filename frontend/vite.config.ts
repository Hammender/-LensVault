import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backendPort = Number(process.env.VITE_BACKEND_PORT || 8000);
const frontendPort = Number(process.env.VITE_FRONTEND_PORT || 5173);

export default defineConfig({
  plugins: [react()],
  server: {
    port: frontendPort,
    proxy: {
      "/api": `http://127.0.0.1:${backendPort}`
    }
  }
});
