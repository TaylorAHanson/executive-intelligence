import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import { loadBrand, type Brand } from './brand.config'

const BRAND_MODULE = 'virtual:brand'

/** Serves `virtual:brand` to the frontend and brands index.html. */
function brand(config: Brand): Plugin {
  return {
    name: 'brand',
    resolveId: (id) => (id === BRAND_MODULE ? `\0${BRAND_MODULE}` : undefined),
    load: (id) => (id === `\0${BRAND_MODULE}` ? `export default ${JSON.stringify(config)}` : undefined),
    transformIndexHtml: (html) => {
      const branded = html.replace('%BRAND_NAME%', config.name)
      return config.favicon ? branded.replace('href="/favicon.svg"', `href="${config.favicon}"`) : branded
    },
  }
}

// The frontend always calls the backend through relative `/api/...` paths.
// In dev, this proxy points those at the local uvicorn process; in production
// FastAPI serves the built bundle from `dist/`, so the same paths resolve
// against the app's own origin with no build-time host baked in.
export default defineConfig({
  plugins: [react(), brand(loadBrand())],
  server: {
    // Uncommon ports on purpose, so running this alongside another local app
    // doesn't collide. Keep the proxy target in step with dev.sh's BACKEND_PORT.
    port: 5180,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8010',
        changeOrigin: true,
      },
    },
  },
})
