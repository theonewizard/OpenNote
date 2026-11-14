import { readFileSync } from "node:fs";
import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vitest/config";

// `npm run dev:mock` runs the app against MSW mocks (src/mocks). The dev server serves
// MSW's worker script from node_modules, so it is never copied into public/ or a build.
const mswWorker: Plugin = {
  name: "msw-worker",
  apply: "serve",
  configureServer(server) {
    server.middlewares.use("/mockServiceWorker.js", (_req, res) => {
      res.setHeader("Content-Type", "text/javascript");
      res.end(readFileSync(path.resolve(import.meta.dirname, "node_modules/msw/lib/mockServiceWorker.js")));
    });
  },
};

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss(), mswWorker],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  // `npm run dev` forwards the API to a backend on this machine (setup.md §5), as nginx
  // does in the web container.
  server: {
    proxy: {
      "/api": process.env.OPENNOTE_API_URL ?? "http://127.0.0.1:8000",
    },
  },
  // The Playwright tests run against `vite preview`; it sends the CSP that nginx sends
  // (infrastructure/containers/web/nginx.conf) so a violation fails the tests too.
  // No API proxy here (preview would inherit server.proxy): the tests mock the API.
  preview: {
    proxy: {},
    headers: {
      "Content-Security-Policy":
        "default-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
    },
  },
  test: {
    environment: "jsdom",
    include: ["tests/unit/**/*.test.{ts,tsx}"],
    setupFiles: ["tests/unit/setup.ts"],
  },
});
