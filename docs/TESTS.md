<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

## Tests: cómo funcionan y sus trampas

### Backend (`tests/backend`, 885 tests)

`conftest.py` define las variables de entorno **antes** de importar `main` (si no,
el import revienta por los secretos obligatorios) y monkeypatchea `requests` con un
`MockRouter`: registras respuestas por `(método, fragmento de URL)` y las rutas se
resuelven **en orden de registro** — registra primero la más específica
(`/calendars/cal-x/calendarView` antes que `/me/calendars`, porque la primera URL
contiene a la segunda). Fixtures: `client`, `auth_headers` (JWT válido),
`mock_requests`, `graph_token` (simula sesión de Graph), `login_attempts_mock`
(simula la tabla `login_attempts` de Supabase con una lista en memoria — sin esto,
cualquier test que llame a `/auth/password` intentaría una llamada de red real). El
limitador genérico (`_rate_buckets`) y los flags WOL se resetean entre tests
automáticamente; los intentos de login NO, porque ya no viven en memoria — cada test
que los necesite los mockea con el fixture de arriba.

**Un test que construya días hacia atrás desde hoy tiene que fijar el reloj**
(`monkeypatch.setattr(main, "_ahora_local", ...)`). Los del informe semanal no lo hacían
y fallaban los lunes y los martes: las semanas van de lunes a domingo, así que "los
últimos cinco días" caen casi todos en la semana anterior y la última sale —bien— como
hueco. Para eso existe `_ahora_local()` como punto único.

Valores del entorno de test: contraseña `1234`, `SECRET_KEY=test-secret-key`,
`HA_POLL_TOKEN=ha-poll-token`, `HEALTH_INGEST_TOKEN=health-token`,
`BRIEF_TOKEN=brief-token`. Lo que se configura por `monkeypatch` en su propio fichero y
no aquí es lo que está APAGADO por defecto en producción (`REVISION_TOKEN`,
`ARREGLO_FIRE_URL`…): así el resto de la suite comprueba de paso que sin configurar no
se enciende solo.

### Frontend (`tests/frontend`, 161 tests)

Vitest + jsdom + Testing Library, configurado en `vite.config.js` (bloque `test`).
Trampas conocidas de jsdom:

- **El input de contraseña tiene `pattern="[0-9]*"`**: jsdom aplica la validación
  de formulario, así que escribir una contraseña con letras en un test **bloquea el
  submit silenciosamente**. Usa contraseñas numéricas en los tests.
- `matchMedia` y `Notification` no existen en jsdom → los stubs están en `setup.js`.
- `window.location.reload` no está implementado: el flujo de login lo llama y jsdom
  imprime "Not implemented: navigation" en la consola. **Es ruido esperado, no un
  fallo** — asegura el comportamiento comprobando `localStorage` en su lugar.
- El test de login renderiza el `Dashboard` completo: cualquier error de runtime en
  el camino de montaje del componente hará fallar esos tests. Es intencionado.

### E2E (`tests/e2e`, Playwright)

`npm run test:e2e`. Navegador real contra el **build de producción** servido por
`vite preview` y el **backend de verdad** — no una imitación:
`tests/e2e/servidor_pruebas.py` importa `backend/main.py` tal cual y solo sustituye
`main.http` por respuestas fijas (mismo truco que `conftest.py`, pero servido por
uvicorn). Por eso este job pilla lo que los otros dos no: que el bundle compilado
arranque, que el contrato entre frontend y backend siga cuadrando, y que no haya
errores de runtime al montar. Los tests fallan si el navegador registra **cualquier**
excepción o error de consola, no solo si falta un texto.

- `playwright.config.js` arranca y apaga los dos servidores solo. `VITE_API_URL` se
  hornea en el bundle, así que el build se hace apuntando ya al backend de pruebas.
- **Los datos del simulador no son de adorno**: llevan una correlación plantada
  (pasos ↔ sueño) para que el motor de patrones tenga algo que encontrar y el test
  compruebe que el widget de salud llega a conclusiones, no solo que se pinta.
- En `_RouterSimulado.RUTAS` **el orden importa**: gana la primera coincidencia y la
  URL de `calendarView` del calendario de clases contiene `/me/calendars`. Ponerlas al
  revés hacía que `/calendar/classes` recibiera calendarios donde espera eventos y
  acabara en un 500 (que además el navegador reporta como error de CORS, porque una
  excepción sin capturar se salta el middleware que pone las cabeceras).
- `PLAYWRIGHT_CHROMIUM_PATH` apunta a un Chromium ya instalado en entornos que traen
  el suyo y no coincide con la versión de Playwright. En CI no se usa: se descarga el
  que toca.
