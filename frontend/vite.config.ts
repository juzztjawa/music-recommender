import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// /api is proxied to the FastAPI backend in dev, so the browser sees one
// origin and the SSE stream isn't subject to CORS.
export default defineConfig({
  plugins: [react()],
  test: { environment: "node", include: ["src/**/*.test.ts", "src/**/*.test.tsx"] },
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8000" },
  },
});
