import { svelte } from '@sveltejs/vite-plugin-svelte'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [svelte()],
  // Relative asset paths so the built index.html works when loaded from a
  // VS Code webview (file-ish origin). Harmless for the Python server at '/'.
  base: './',
  server: {
    // `pnpm dev` against a backend started with `raggie code web` (port 8765):
    // the app POSTs JSON-RPC to '/', so forward POSTs to the backend and let
    // Vite keep serving GETs (modules, HMR).
    proxy: {
      '/': {
        target: 'http://127.0.0.1:8765',
        bypass: (req) => {
          if (req.method !== 'POST') return req.url
        },
      },
    },
  },
})
