import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

// De qué commit se construyó esto. Lo pone Vercel en el entorno del build
// (VERCEL_GIT_COMMIT_SHA) y aquí se hornea en el bundle, porque es la ÚNICA forma de que
// el frontend sepa qué versión de sí mismo está sirviendo: el despliegue de Vercel no
// pasa por el backend, así que nadie más puede contarlo. Lo usa la pestaña Despliegue de
// la zona dev (docs/ZONA_DEV.md). En local no hay tal variable y queda "dev", que es la
// verdad: lo que corre es lo que haya en el disco, y eso no tiene sha.
const COMMIT = process.env.VERCEL_GIT_COMMIT_SHA || "dev";

// Qué rutas son de otra copia del repositorio: las que cuelgan de `.claude/worktrees/`
// DE ESTE checkout, no de cualquier sitio. Un glob tipo `**/.claude/worktrees/**` no
// vale: chokidar lo compara con la ruta absoluta, y dentro de un worktree la de TODOS
// sus ficheros pasa por `.claude/worktrees/`, así que se ignoraba a sí mismo y
// `npm run dev` no vigilaba nada (ni HMR ni recargando). Función y no glob anclado
// porque la ruta del checkout puede llevar caracteres que un glob lee como sintaxis
// (paréntesis, corchetes). chokidar la llama con la ruta ya en barras normales; se
// normaliza igual por si no.
export function esDeOtraCopia(raiz) {
  const copias = raiz.replaceAll('\\', '/').replace(/\/*$/, '') + '/.claude/worktrees'
  return (ruta) => {
    const r = String(ruta).replaceAll('\\', '/')
    return r === copias || r.startsWith(copias + '/')
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Como una VITE_* más y no como un global propio: así se lee con
  // `import.meta.env.VITE_COMMIT_SHA`, igual que el resto de la configuración de
  // instancia, y no hay que enseñarle un nombre nuevo a ESLint.
  define: {
    'import.meta.env.VITE_COMMIT_SHA': JSON.stringify(COMMIT),
  },
  // `.claude/worktrees/` guarda copias enteras del repositorio dentro del checkout
  // principal. Sin estas dos líneas, `npm run dev` desde la raíz vigilaba todos sus
  // ficheros y, al no haber entradas explícitas, el pre-empaquetado de dependencias
  // tomaba como entrada CADA `index.html` que encontrara (`**/*.html`), así que escaneaba
  // también el dashboard de cada copia. La única entrada de la app es la de la raíz.
  server: {
    watch: { ignored: [esDeOtraCopia(dirname(fileURLToPath(import.meta.url)))] },
  },
  optimizeDeps: {
    entries: ['index.html'],
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/frontend/setup.js'],
    include: ['tests/frontend/**/*.test.{js,jsx}'],
  },
})
