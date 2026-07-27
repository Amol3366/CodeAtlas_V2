/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The dev server proxies `/v1` to the loopback API. The API stays bound to
// loopback and registers no CORS middleware, so the proxy — not a relaxed
// server policy — is what lets the browser talk to it during development.
// The end-to-end suites serve the built assets from `vite preview` and proxy
// `/v1` to the harness backend, so the browser sees one origin — exactly the
// arrangement the packaged build will have. Proxying rather than relaxing CORS
// keeps the API's "no CORS middleware" property under test rather than around
// it.
const E2E_API_PORT = process.env["CODEATLAS_E2E_API_PORT"] ?? "8123";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/v1": {
        target: "http://127.0.0.1:8000",
        changeOrigin: false,
      },
    },
  },
  preview: {
    port: 4173,
    strictPort: true,
    proxy: {
      "/v1": {
        target: `http://127.0.0.1:${E2E_API_PORT}`,
        changeOrigin: false,
      },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: true,
    // Playwright specs live in `e2e/` and drive a real browser. Vitest would
    // otherwise collect them by its default glob and fail them under jsdom.
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});
