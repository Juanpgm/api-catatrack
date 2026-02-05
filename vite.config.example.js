// Configuración de Vite con Proxy para desarrollo local
// Este archivo debe estar en la raíz del proyecto frontend

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],

  // Configuración del servidor de desarrollo
  server: {
    port: 5174,

    // Configuración de proxy para evitar problemas de CORS en desarrollo
    proxy: {
      // Todas las peticiones a /api se redirigen al backend
      "/api": {
        target: "https://web-production-2d737.up.railway.app",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
        secure: false,
        configure: (proxy, options) => {
          proxy.on("error", (err, req, res) => {
            console.log("Proxy error:", err);
          });
          proxy.on("proxyReq", (proxyReq, req, res) => {
            console.log("Sending Request:", req.method, req.url);
          });
          proxy.on("proxyRes", (proxyRes, req, res) => {
            console.log("Received Response:", proxyRes.statusCode, req.url);
          });
        },
      },
    },
  },

  // Variables de entorno
  define: {
    "process.env": {},
  },
});
