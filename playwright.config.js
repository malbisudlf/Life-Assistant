import { defineConfig, devices } from '@playwright/test'

// E2E: navegador real contra el frontend construido y el backend real (con los
// servicios externos simulados por tests/e2e/servidor_pruebas.py).
//
// Los tests de vitest corren sobre jsdom con fetch mockeado: comprueban lógica, no la
// app montada. Esto cubre el hueco que quedaba — que el dashboard arranque de verdad,
// pinte y no se rompa en el camino de login.
//
// El frontend se sirve con `vite preview` sobre el build de producción, no con el
// servidor de desarrollo: es lo que acaba en Vercel, y así el test también valida que
// el bundle compilado funciona.
const PUERTO_API  = 8000
const PUERTO_WEB  = 4173
const URL_API     = `http://127.0.0.1:${PUERTO_API}`

export default defineConfig({
  testDir: './tests/e2e',
  // En CI no se reintenta a ciegas: un test que solo pasa a la segunda es un test que
  // esconde una carrera. Localmente tampoco.
  retries: 0,
  workers: 1,
  reporter: process.env.CI ? [['github'], ['list']] : [['list']],
  timeout: 30_000,
  expect: { timeout: 10_000 },

  use: {
    baseURL: `http://127.0.0.1:${PUERTO_WEB}`,
    // Solo se guardan al fallar: en verde no interesan y engordan el artefacto.
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        // En CI se descarga el Chromium que le toca a esta versión de Playwright
        // (`npx playwright install`). Algunos entornos ya traen uno preinstalado que
        // no coincide con esa versión: ahí se apunta con PLAYWRIGHT_CHROMIUM_PATH en
        // vez de descargar otro. Sin la variable, comportamiento estándar.
        ...(process.env.PLAYWRIGHT_CHROMIUM_PATH
          ? { launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH } }
          : {}),
      },
    },
  ],

  // Playwright arranca y espera a los dos servidores, y los apaga al terminar.
  webServer: [
    {
      command: `python tests/e2e/servidor_pruebas.py ${PUERTO_API}`,
      url: `${URL_API}/`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      // VITE_API_URL se hornea en el bundle, así que hay que construir apuntando ya
      // al backend de pruebas; no vale ponerlo solo al servir.
      command: `VITE_API_URL=${URL_API} npm run build && npm run preview -- --port ${PUERTO_WEB} --strictPort`,
      url: `http://127.0.0.1:${PUERTO_WEB}`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
})
