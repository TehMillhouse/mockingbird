import { resolve } from "node:path";
import { defineConfig } from "vite";

// The API runs separately (`mb serve`); in development its routes are proxied.
export default defineConfig({
  // relative asset URLs, so the built app can be served under a path prefix
  base: "./",
  build: {
    // abcjs, OSMD and Tone.js make up almost all of the bundle; splitting them buys nothing locally
    chunkSizeWarningLimit: 2000,
    rollupOptions: {
      input: {
        levels: resolve(__dirname, "index.html"),
        piece: resolve(__dirname, "piece.html"),
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/levels": "http://127.0.0.1:8000",
      "/pieces": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
});
