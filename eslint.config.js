import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  // `.claude/worktrees/` son copias enteras del repositorio (una por sesión en paralelo)
  // dentro del checkout principal: sin esto, `npm run lint` desde la raíz las recorre
  // todas, tarda varias veces más y avisa de errores que no son del árbol que se revisa.
  // `test-results/` y `playwright-report/` son la salida del E2E, no código.
  globalIgnores(['dist', '.claude/worktrees/', 'test-results/', 'playwright-report/']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
  },
  {
    // La config de Playwright y los tests E2E corren en Node, no en el navegador:
    // usan `process` para distinguir CI. El código de dentro de page.evaluate() sí es
    // de navegador, así que aquí hacen falta los dos conjuntos de globales.
    // `vite.config.js` entra por lo mismo: lee `process.env.VERCEL_GIT_COMMIT_SHA` para
    // hornear en el bundle de qué commit se construyó (la pestaña Despliegue de la zona
    // dev), y eso pasa en Node, durante el build, no en el navegador.
    files: ['playwright.config.js', 'vite.config.js', 'tests/e2e/**/*.js'],
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
    },
  },
  {
    // Código de claude-phone que vive aquí para no perderse y corre en Node, en
    // `caja` (ver telefono/PARCHES.md). CommonJS, como el resto de claude-phone.
    files: ['telefono/**/*.js'],
    languageOptions: {
      sourceType: 'commonjs',
      globals: globals.node,
    },
  },
])
