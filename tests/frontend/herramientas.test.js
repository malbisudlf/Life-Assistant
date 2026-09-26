// La configuración de las herramientas de desarrollo (ESLint, Vite, npm). No prueba la
// app: prueba que la verificación de antes de cada commit mira lo que tiene que mirar y
// nada más. Se queda en el entorno jsdom de siempre (setup.js da por hecho que hay
// `window`); los módulos de Node se importan igual.
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { ESLint } from 'eslint'
import { describe, expect, it } from 'vitest'
import configVite, { esDeOtraCopia } from '../../vite.config.js'

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), '..', '..')

describe('ESLint', () => {
  const eslint = new ESLint({ cwd: RAIZ })

  it('no se mete en las copias del repositorio de .claude/worktrees', async () => {
    // Cada una es un checkout entero: recorrerlas multiplicaba el tiempo del lint y
    // traía errores de otro árbol al que se estaba revisando.
    expect(await eslint.isPathIgnored(join(RAIZ, '.claude/worktrees/otra/src/components/Dashboard.jsx'))).toBe(true)
  })

  it('sigue mirando el código de verdad', async () => {
    expect(await eslint.isPathIgnored(join(RAIZ, 'src/components/Dashboard.jsx'))).toBe(false)
    expect(await eslint.isPathIgnored(join(RAIZ, 'tests/e2e/dashboard.spec.js'))).toBe(false)
  })

  it('npm run lint falla con un solo warning, igual que en CI', () => {
    const paquete = JSON.parse(readFileSync(join(RAIZ, 'package.json'), 'utf8'))
    expect(paquete.scripts.lint).toMatch(/--max-warnings 0\b/)
  })
})

describe('Vite', () => {
  // chokidar llama a cada entrada de `ignored` con la ruta absoluta en barras normales.
  // Se prueba lo que decide con rutas de verdad, no qué cadena hay en el array: el glob
  // `**/.claude/worktrees/**` estaba en el array y, desde un worktree, se ignoraba
  // también a sí mismo.
  const ignorada = (ruta) => configVite.server.watch.ignored.some((m) => m(ruta.replaceAll('\\', '/')))

  it('el servidor de desarrollo no vigila las copias de .claude/worktrees', () => {
    expect(ignorada(join(RAIZ, '.claude/worktrees/otra/src/components/Dashboard.jsx'))).toBe(true)
    expect(ignorada(join(RAIZ, '.claude/worktrees'))).toBe(true)
  })

  it('sigue vigilando el código de su propio checkout', () => {
    expect(ignorada(join(RAIZ, 'src/components/Dashboard.jsx'))).toBe(false)
    expect(ignorada(RAIZ)).toBe(false)
  })

  it('desde un worktree no se ignora a sí mismo', () => {
    // Las sesiones en paralelo trabajan justo ahí, con la raíz DENTRO de otro
    // `.claude/worktrees/`: solo cuenta el de su propio checkout.
    const esCopia = esDeOtraCopia('/repo/.claude/worktrees/sesion')
    expect(esCopia('/repo/.claude/worktrees/sesion/src/components/Dashboard.jsx')).toBe(false)
    expect(esCopia('/repo/.claude/worktrees/sesion')).toBe(false)
    expect(esCopia('/repo/.claude/worktrees/sesion/.claude/worktrees/otra/src/x.jsx')).toBe(true)
    expect(esCopia('/repo/.claude/worktrees/otra/src/x.jsx')).toBe(false)
  })

  it('acepta la raíz con barras de Windows y caracteres de glob en la ruta', () => {
    const esCopia = esDeOtraCopia('C:\\Proyectos (1)\\app [dev]\\')
    expect(esCopia('C:/Proyectos (1)/app [dev]/.claude/worktrees/otra/src/x.jsx')).toBe(true)
    expect(esCopia('C:\\Proyectos (1)\\app [dev]\\.claude\\worktrees\\otra')).toBe(true)
    expect(esCopia('C:/Proyectos (1)/app [dev]/src/x.jsx')).toBe(false)
    // Un nombre que solo EMPIEZA igual no es el directorio de copias.
    expect(esCopia('C:/Proyectos (1)/app [dev]/.claude/worktrees-viejo/x.jsx')).toBe(false)
  })

  it('solo pre-empaqueta dependencias desde el index.html de la raíz', () => {
    // Sin entradas explícitas, Vite toma todo `**/*.html` como entrada, y eso incluía el
    // index.html de cada copia del repositorio de .claude/worktrees.
    expect(configVite.optimizeDeps.entries).toEqual(['index.html'])
  })
})
