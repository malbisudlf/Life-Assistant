import { test, expect } from '@playwright/test'

// Camino crítico de la aplicación en un navegador real: login → dashboard → datos
// pintados → modal de salud con los patrones del histórico.
//
// Lo que cubre esto y no cubren los tests de vitest: que el bundle de producción
// arranque, que el contrato entre frontend y backend siga cuadrando (aquí responde el
// backend de verdad, no un fetch mockeado) y que no haya errores de runtime al montar.
// Todo eso se rompía sin que se enterara nadie hasta abrir la app en el móvil.

const PASSWORD = '1234'   // la del servidor_pruebas.py

// Cualquier excepción no capturada del navegador tumba el test, aunque la UI parezca
// pintarse bien: un componente que revienta a mitad deja el resto a medias en silencio.
test.beforeEach(async ({ page }) => {
  const errores = []
  page.on('pageerror', e => errores.push(e.message))
  page.on('console', m => { if (m.type() === 'error') errores.push(m.text()) })
  page.erroresDeNavegador = errores
})

async function entrar(page) {
  await page.goto('/')
  await expect(page.getByText('Acceso privado')).toBeVisible()
  await page.getByPlaceholder('Contraseña').fill(PASSWORD)
  await page.getByRole('button', { name: 'Entrar' }).click()
  // Tras el login la app recarga; el dashboard queda cuando aparece un widget.
  await expect(page.locator('[data-card]').first()).toBeVisible({ timeout: 15_000 })
}

test('la pantalla de login rechaza una contraseña incorrecta', async ({ page }) => {
  await page.goto('/')
  await page.getByPlaceholder('Contraseña').fill('9999')
  await page.getByRole('button', { name: 'Entrar' }).click()
  await expect(page.getByText('Contraseña incorrecta')).toBeVisible()
  // Y no deja pasar: sigue en el login.
  await expect(page.getByText('Acceso privado')).toBeVisible()
})

test('login y carga del dashboard con datos del backend', async ({ page }) => {
  await entrar(page)

  // El token queda guardado: es lo que mantiene la sesión entre recargas.
  const token = await page.evaluate(() => localStorage.getItem('la_token'))
  expect(token).toBeTruthy()

  // Datos que vienen del backend, no del bundle: si el contrato se rompe, esto falla.
  await expect(page.getByText('Evento de prueba E2E').first()).toBeVisible({ timeout: 15_000 })

  expect(page.erroresDeNavegador).toEqual([])
})

test('el widget de salud llega a conclusiones y abre el análisis completo', async ({ page }) => {
  await entrar(page)

  const widget = page.locator('[data-card="health_hub"]')
  await expect(widget).toBeVisible({ timeout: 15_000 })
  // "Sin datos de salud aún" significaría que las métricas no llegaron o que el motor
  // de conclusiones no sacó nada de ellas — las dos cosas son un fallo real.
  await expect(widget).not.toContainText('Sin datos de salud aún')
  await expect(widget).not.toContainText('Cargando...')

  await widget.click()
  await expect(page.getByText('Análisis de salud')).toBeVisible()

  // El panel de patrones pide el histórico largo aparte, al abrir el modal.
  const patrones = page.getByText('Patrones a largo plazo')
  await expect(patrones).toBeVisible()
  await expect(page.getByText('Analizando el histórico…')).toHaveCount(0, { timeout: 15_000 })

  expect(page.erroresDeNavegador).toEqual([])
})

test('el dashboard se pinta también en móvil', async ({ page }) => {
  // El dashboard se usa sobre todo desde el móvil, y tiene un modo simplificado y una
  // rejilla propia para pantallas estrechas: merece comprobarse en su tamaño real.
  await page.setViewportSize({ width: 390, height: 844 })
  await entrar(page)

  await expect(page.locator('[data-card]').first()).toBeVisible()
  // Nada debe desbordar a lo ancho: el scroll horizontal en móvil es un bug visible.
  const desborda = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
  )
  expect(desborda, 'la página hace scroll horizontal en móvil').toBe(false)

  expect(page.erroresDeNavegador).toEqual([])
})

test('Jarvis consulta la agenda y deja una acción por confirmar', async ({ page }) => {
  await entrar(page)

  const entrada = page.getByPlaceholder('Habla con Jarvis')
  await expect(entrada).toBeVisible()

  // Camino 1: consulta. El backend ejecuta la herramienta `agenda` de verdad contra el
  // Graph simulado, así que si el contrato de /calendar/events se rompe, falla aquí.
  await entrada.fill('¿qué tengo hoy?')
  await entrada.press('Enter')
  await expect(page.getByText('Hoy tienes el Evento de prueba E2E.')).toBeVisible({ timeout: 15_000 })
  // La herramienta usada se muestra bajo la respuesta: es cómo se ve que consultó y no
  // se lo inventó.
  await expect(page.getByText('agenda', { exact: true })).toBeVisible()

  // Camino 2: acción que NO se ejecuta sola. Tiene que aparecer el botón de confirmar
  // con la descripción construida a partir de los argumentos reales.
  await entrada.fill('apunta el dentista')
  await entrada.press('Enter')
  await expect(page.getByText(/Crear "Dentista" el \d{2}\/\d{2}\/\d{4} a las 17:00/)).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole('button', { name: 'Confirmar' })).toBeVisible()

  expect(page.erroresDeNavegador).toEqual([])
})

test('el widget de finanzas pinta la cartera de Indexa y el saldo de Revolut', async ({ page }) => {
  await entrar(page)

  const widget = page.locator('[data-card="finanzas"]')
  await expect(widget).toBeVisible({ timeout: 15_000 })
  // "Sin conectar" significaría que el backend no llegó a preguntar, y "No se pudo
  // consultar" que el contrato con la API cambió: las dos cosas son un fallo real. Se
  // comprueba en toda la tarjeta porque ahora hay dos integraciones dentro (Indexa y
  // Revolut) y las dos tienen que salir conectadas.
  await expect(widget).not.toContainText('Sin conectar')
  await expect(widget).not.toContainText('No se pudo consultar')

  // Los números salen del backend, que ha agregado las posiciones de la cartera simulada.
  await expect(widget).toContainText('12.500 €')
  await expect(widget).toContainText('+1500 €')
  await expect(widget).toContainText('Acciones')

  // El saldo de Revolut vive en el mismo widget, aparte de la cartera — como una fila
  // más de la lista unificada, sin su propia caja ni título.
  await expect(widget).toContainText('Revolut')
  await expect(widget).toContainText('80 €')

  // El reparto del patrimonio: con dos fuentes (Indexa y Revolut) ya se pinta, y los
  // pesos los calcula el frontend sobre lo que devolvió el backend — 12.500 € contra
  // 79,70 €. Que salga el porcentaje pequeño es la parte que importa: una porción del
  // 0,6 % tiene que seguir teniendo nombre en la leyenda aunque casi no se vea.
  // (El nombre y el porcentaje son dos <span> pegados, sin espacio en el DOM: la
  // separación es del layout, así que se comprueban por separado.)
  await expect(widget).toContainText('Dónde está el dinero')
  await expect(widget).toContainText('Indexa Capital')
  await expect(widget).toContainText('99,4 %')
  await expect(widget).toContainText('0,6 %')

  // Y al señalar una porción sale su tooltip, con el nombre, el porcentaje y el importe.
  // El hover va por coordenadas sobre el SVG y no sobre el <circle>: Playwright apunta al
  // centro del elemento, y el centro de un círculo de donut es el agujero, donde no hay
  // trazo que reciba el puntero. (64, 64) es el centro de los 128 px, así que x = 118 cae
  // en el anillo de la derecha — dentro de la porción de Indexa, que ocupa casi todo.
  const donut = widget.locator('[data-donut="patrimonio"]')
  await expect(widget.locator('[data-donut-tooltip]')).toHaveCount(0)
  await donut.hover({ position: { x: 118, y: 64 } })
  await expect(widget.locator('[data-donut-tooltip]')).toContainText('Indexa Capital')
  await expect(widget.locator('[data-donut-tooltip]')).toContainText('12.500 €')

  // El detalle está plegado a propósito: se despliega a mano.
  await expect(widget).not.toContainText('Vanguard Global')
  await widget.getByRole('button', { name: 'Ver posiciones' }).click()
  await expect(widget).toContainText('Vanguard Global Stock Index Fund')

  expect(page.erroresDeNavegador).toEqual([])
})

test('el widget de alarmas pinta la alarma de respaldo y deja quitarla', async ({ page }) => {
  await entrar(page)

  const widget = page.locator('[data-card="alarmas"]')
  await expect(widget).toBeVisible({ timeout: 15_000 })

  // La hora viaja en UTC desde Supabase y el backend la pasa a local; el frontend solo
  // la escribe en palabras. Que salga "mañana a las 8:30" y no "hoy" ni un 6:30 prueba
  // los dos saltos a la vez, que es donde vive el bug de zona horaria de siempre.
  await expect(widget).toContainText('mañana a las 08:30')
  await expect(widget).toContainText('Entrenar')
  await expect(widget).toContainText('puesta')

  // Lo que distingue esta alarma de la del móvil, dicho donde se pone.
  await expect(widget).toContainText('te despierta la casa')

  // Ninguna está sonando, así que el botón grande no debe aparecer: si saliera, estaría
  // ofreciendo callar algo que no suena.
  await expect(widget.getByRole('button', { name: 'Estoy despierto' })).toHaveCount(0)

  expect(page.erroresDeNavegador).toEqual([])
})

test('la zona dev dice qué código corre y qué corre solo', async ({ page }) => {
  await entrar(page)

  await page.getByRole('button', { name: '🛠' }).first().click()

  // Despliegue: el sha del backend (aquí, el VERSION simulado) contra el main de GitHub.
  // Lo que se comprueba es que la comparación llega pintada, que es lo único que esta
  // pestaña tiene que hacer bien — y que NO ofrece desplegar, porque no puede.
  await page.getByRole('button', { name: 'Despliegue' }).click()
  await expect(page.getByText('1 commit por desplegar', { exact: false })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText('Reconstruir', { exact: false })).toBeVisible()
  await expect(page.getByRole('button', { name: /desplegar|reconstruir/i })).toHaveCount(0)

  // Crons: los tres programados con su último run, y los sondeos, que aquí no ha hecho
  // nadie porque el backend acaba de arrancar — y eso se dice, no se pinta como avería.
  await page.getByRole('button', { name: 'Crons' }).click()
  await expect(page.getByText('Copia de Supabase')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText('Revisión nocturna del código')).toBeVisible()
  await expect(page.getByText('/ha/avisos-pending')).toBeVisible()

  expect(page.erroresDeNavegador).toEqual([])
})
