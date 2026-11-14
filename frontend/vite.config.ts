import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    fs: { allow: [".."] },
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  test: {
    // Only test workers use UTC; application timestamp formatting remains local.
    env: { TZ: "UTC" },
    environment: "jsdom",
    setupFiles: "./src/test-setup.ts",
  },
});
