import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// De qué commit se construyó esto. Lo pone Vercel en el entorno del build
// (VERCEL_GIT_COMMIT_SHA) y aquí se hornea en el bundle, porque es la ÚNICA forma de que
// el frontend sepa qué versión de sí mismo está sirviendo: el despliegue de Vercel no
// pasa por el backend, así que nadie más puede contarlo. Lo usa la pestaña Despliegue de
// la zona dev (docs/ZONA_DEV.md). En local no hay tal variable y queda "dev", que es la
// verdad: lo que corre es lo que haya en el disco, y eso no tiene sha.
const COMMIT = process.env.VERCEL_GIT_COMMIT_SHA || "dev";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Como una VITE_* más y no como un global propio: así se lee con
  // `import.meta.env.VITE_COMMIT_SHA`, igual que el resto de la configuración de
  // instancia, y no hay que enseñarle un nombre nuevo a ESLint.
  define: {
    'import.meta.env.VITE_COMMIT_SHA': JSON.stringify(COMMIT),
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/frontend/setup.js'],
    include: ['tests/frontend/**/*.test.{js,jsx}'],
  },
})
