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
// Overridables por entorno: en una máquina de desarrollo el 8000 suele estar ocupado
// por el backend local, y en Windows un uvicorn muerto puede dejar el socket en
// LISTENING con un PID que ya no existe, sin forma cómoda de liberarlo. En CI se usan
// los de siempre.
const PUERTO_API  = Number(process.env.E2E_PUERTO_API) || 8000
const PUERTO_WEB  = Number(process.env.E2E_PUERTO_WEB) || 4173
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
  // `stdout/stderr: 'pipe'` para que su salida acabe en el log: sin esto, un servidor
  // que no arranca solo deja un "Timed out waiting from config.webServer" sin motivo.
  webServer: [
    {
      command: `python tests/e2e/servidor_pruebas.py ${PUERTO_API}`,
      url: `${URL_API}/`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      // VITE_API_URL se hornea en el bundle, así que hay que construir apuntando ya
      // al backend de pruebas; no vale ponerlo solo al servir.
      //
      // --host 127.0.0.1 explícito: por defecto `vite preview` escucha en `localhost`,
      // que en los runners de CI puede resolver a ::1 mientras Playwright sondea la
      // 127.0.0.1 — y entonces el servidor está vivo pero nadie lo encuentra.
      command: `VITE_API_URL=${URL_API} npm run build && npm run preview -- --host 127.0.0.1 --port ${PUERTO_WEB} --strictPort`,
      url: `http://127.0.0.1:${PUERTO_WEB}`,
      reuseExistingServer: !process.env.CI,
      // Holgado a propósito: aquí dentro entra un build de producción completo, y un
      // runner frío tarda bastante más que una máquina de desarrollo.
      timeout: 180_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
  ],
})
