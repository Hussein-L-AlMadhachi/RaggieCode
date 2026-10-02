import { svelte } from '@sveltejs/vite-plugin-svelte'
import { defineConfig } from 'vitest/config'

// Mirrors the shape used by vscode-extension/vitest.config.ts (a dedicated
// config file rather than a `test` key inside vite.config.ts). Two differences
// are required here:
//   - `svelte()` so `.svelte.ts` runes files ($state) compile instead of
//     throwing a bare-identifier ReferenceError.
//   - jsdom, because src/lib/bridge.ts reads `window.location` at module
//     scope and src/lib/theme.svelte.ts calls window.matchMedia.
// The dev server proxy from vite.config.ts is deliberately not inherited.
export default defineConfig({
  plugins: [svelte()],
  resolve: {
    conditions: ['browser'],
  },
  test: {
    include: ['tests/**/*.test.ts'],
    environment: 'jsdom',
  },
})
