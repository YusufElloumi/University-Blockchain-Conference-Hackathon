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
  ],
  // The program's IDL (its public interface description) lives in ../onchain/idl.
  server: { fs: { allow: [".."] } },
});
