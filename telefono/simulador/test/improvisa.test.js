/**
 * El Mikel que improvisa (improvisa.js): sin Codex de verdad. Lo que se comprueba es lo que
 * no puede romperse: que Codex va sin terminal, que lo inventado no trae herramientas que
 * no existen y que una llamada improvisada se corre turno a turno y se corta al colgar.
 *
 *   node --test telefono/simulador/test/
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

const improvisa = require('../improvisa');
const { crearMundo } = require('../mundo');
const { correrCaso } = require('../simular');

test('codex: sin terminal, sin web, sin la config del usuario', function () {
  const funciones = improvisa.funcionesConocidas('shell_tool  stable true\nunified_exec stable true\napps stable true\n');
  const args = improvisa.argsCodex('/t/s.txt', '/t/e.json', '/t/o.json', '/t', funciones, '');
  const apagado = args.filter(function (a, i) { return args[i - 1] === '--disable'; });
  assert.deepStrictEqual(apagado.sort(), ['apps', 'shell_tool', 'unified_exec']);
  assert.ok(args.includes('--ignore-user-config') && args.includes('--ephemeral'));
  assert.strictEqual(args[args.indexOf('--sandbox') + 1], 'read-only');
  assert.ok(args.includes('web_search="disabled"'));
  assert.ok(!args.some(function (a) { return /mcp_servers|dangerously|bypass/.test(a); }));
  assert.strictEqual(args[args.indexOf('--output-schema') + 1], '/t/e.json');
});

test('inventar: descarta herramientas que no existen y repite ids', function () {
  const casos = improvisa.aCasos({ casos: [
    { id: 'Pon Peli!', objetivo: 'ver una peli', primera: 'ponme algo', modo: 'normal', ruido: 'limpio',
      mundo: [{ herramienta: 'cine_proponer', respuesta_json: '{"pelis":["A"]}' },
              { herramienta: 'abrir_puerta_del_vecino', respuesta_json: '{}' }] },
    { id: 'pon-peli', objetivo: 'otra', primera: 'y otra', modo: 'coche', ruido: 'coche', mundo: [] },
    { id: 'vacio', objetivo: '', primera: '', modo: 'normal', ruido: 'limpio', mundo: [] },
  ] }, [{ name: 'cine_proponer' }]);
  assert.strictEqual(casos.length, 2);
  assert.deepStrictEqual(casos[0].mundo, { cine_proponer: { pelis: ['A'] } });
  assert.strictEqual(casos[0].id, 'improvisa-pon-peli-');
  assert.notStrictEqual(casos[0].id, casos[1].id);
  assert.strictEqual(casos[1].modo, 'coche');
});

test('una llamada improvisada: Mikel habla hasta colgar', async function () {
  const mundo = crearMundo({ catalogo: [{ name: 'agenda' }] });
  const frases = [{ dice: 'a las cuántas?', fin: false }, { dice: '', fin: true }];
  const vistos = [];
  const d = {
    mundo: mundo, ruido: 'limpio', maxTurnos: 6,
    confirmacion: { pedidoDeConfirmacion: function () { return null; },
                    preguntarSiLoPide: async function () { return {}; } },
    avisos: { pasiva: '', interrupcion: '' },
    improvisar: async function (caso, turnos) { vistos.push(turnos.length); return frases.shift(); },
    preguntar: async function () { return { response: '🗣️ VOICE_RESPONSE: Mañana tienes dentista.' }; },
    colgar: async function () {},
  };
  const traza = await correrCaso({ id: 'x', improvisa: true, objetivo: 'saber cuándo es el dentista',
                                   primera: 'cuándo tengo el dentista' }, d, 0);
  assert.deepStrictEqual(traza.turnos.map(function (t) { return t.dicho; }),
                         ['cuándo tengo el dentista', 'a las cuántas?']);
  assert.deepStrictEqual(vistos, [1, 2]);
});

test('la conversación que lee Codex', function () {
  const texto = improvisa.escribirConversacion([{ dicho: 'hola', voz: ['Dígame.'], llamada: [] },
                                                { dicho: 'y?', voz: [], llamada: [], error: 'Claude no contestó' }]);
  assert.match(texto, /1\. Mikel: hola\n {3}Jarvis: Dígame\./);
  assert.match(texto, /\(Claude no contestó\)/);
});

test('el repaso cuenta la noche del simulador, y no la de hace días', function () {
  const { simulacionDeAnoche } = require('../repasar');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'sim-noche-'));
  try {
    assert.strictEqual(simulacionDeAnoche(dir, Date.now()), null);
    fs.writeFileSync(path.join(dir, 'ultima-noche.json'), JSON.stringify({
      cuando: new Date().toISOString(), total: 6, bien: 5,
      mal: [{ id: 'improvisa-cine', objetivo: 'ver una peli', fallos: ['roce: se repitió'] }] }));
    const r = simulacionDeAnoche(dir, Date.now());
    assert.strictEqual(r.mal, 1);
    assert.match(r.informe, /5 de 6/);
    assert.match(r.linea, /5\/6/);
    assert.strictEqual(simulacionDeAnoche(dir, Date.now() + 13 * 3600 * 1000), null);
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});
