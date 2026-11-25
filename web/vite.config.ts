/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The dev server sends API calls to `make run` on this machine, so the browser sees one origin
// and the API needs no CORS setting. The built app is served by the API itself.
const API = 'http://127.0.0.1:8710'

export default defineConfig({
  plugins: [react()],
  build: {
    // The app's CSP lets styles, scripts and fonts come from its own origin only, and a data: URL
    // is not that. Every built file stays a file.
    assetsInlineLimit: 0,
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: { '/v1': API, '/healthz': API },
  },
  test: {
    environment: 'jsdom',
    restoreMocks: true,
    unstubGlobals: true,
    setupFiles: ['./src/test/setup.ts'],
    coverage: {
      provider: 'v8',
      // The app's logic, not its markup. Each file has to reach the thresholds on its own, so a
      // well-covered file cannot cover for another.
      include: [
        'src/api/client.ts',
        'src/app/route.ts',
        'src/app/areas.ts',
        'src/app/useInboxCount.ts',
      ],
      reporter: ['text'],
      thresholds: { perFile: true, statements: 80, branches: 80, functions: 80, lines: 80 },
    },
  },
})
