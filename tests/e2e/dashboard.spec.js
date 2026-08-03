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
