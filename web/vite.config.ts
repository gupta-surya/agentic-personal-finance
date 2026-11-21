import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Dev only: the render API runs locally (uvicorn finance_agent.serve_charts:app). It only
    // answers Host/Origin 127.0.0.1:8000, so the proxy presents itself as that.
    proxy: Object.fromEntries(
      ["/charts", "/ask"].map((path) => [
        path,
        {
          target: "http://127.0.0.1:8000",
          changeOrigin: true,
          headers: { Origin: "http://127.0.0.1:8000" },
        },
      ]),
    ),
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
  },
});
