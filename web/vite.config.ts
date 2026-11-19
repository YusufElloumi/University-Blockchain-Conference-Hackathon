import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { nodePolyfills } from "vite-plugin-node-polyfills";

export default defineConfig({
  // One .env file at the repo root serves the API and the web app. Only VITE_ names reach the browser.
  envDir: "..",
  // Relative file addresses, so the built app works under any folder (GitHub Pages serves it from /<repo name>/).
  base: "./",
  plugins: [
    react(),
    // The Solana and Privy libraries expect a few Node.js globals (Buffer, process) in the browser.
    nodePolyfills({ include: ["buffer", "process"], globals: { Buffer: true, global: true, process: true } }),
    // Dev server only: send /privacy and /terms to their folder pages (Render does this with rewrites in render.yaml).
    {
      name: "legal-page-slash",
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          const match = req.url?.match(/^\/(privacy|terms)(\?.*)?$/);
          if (!match) return next();
          res.statusCode = 302;
          res.setHeader("Location", `/${match[1]}/${match[2] ?? ""}`);
          res.end();
        });
      },
    },
  ],
  // Three pages: the app, and the public legal pages at /privacy and /terms.
  build: {
    rollupOptions: {
      input: { main: "index.html", privacy: "privacy/index.html", terms: "terms/index.html" },
    },
  },
  // The program's IDL (its public interface description) lives in ../onchain/idl.
  server: { fs: { allow: [".."] } },
});
