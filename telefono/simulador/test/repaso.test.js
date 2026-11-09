/**
 * Tests del repaso de llamadas (docs/SIMULADOR.md): `node --test telefono/simulador/test/`.
 * Las llamadas de aquí son inventadas.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

const { leerSesion, separarPrompt, fricciones, casoDe, resumen, parecido } = require('../friccion');
const { mirar, escribirLlamada, guardarCasos } = require('../repasar');

const T0 = Date.parse('2026-11-09T18:00:00Z');

function usuario(seg, texto) {
  return JSON.stringify({ type: 'user', timestamp: new Date(T0 + seg * 1000).toISOString(), message: { content: texto } });
}
function jarvis(seg, bloques) {
  return JSON.stringify({ type: 'assistant', timestamp: new Date(T0 + seg * 1000).toISOString(), message: { content: bloques } });
}
function resultado(seg, texto, error) {
  return JSON.stringify({ type: 'user', timestamp: new Date(T0 + seg * 1000).toISOString(),
    message: { content: [{ type: 'tool_result', content: texto, is_error: Boolean(error) }] } });
}
const AHORA = '[Ahora: lunes, 9 de noviembre, 19:00] ';

function llamada() {
  return [
    usuario(0, '[DEVICE IDENTITY] Eres Jarvis.\n[CONTEXTO AL DESCOLGAR]\nMañana: [10:00] Dentista\n[FIN DEL CONTEXTO]\n\n' + AHORA + 'pon una alarma a las siete'),
    jarvis(2, [{ type: 'text', text: '🗣️ VOICE_RESPONSE: ¿De la mañana o de la tarde, señor?' }]),
    usuario(10, AHORA + 'que pongas una alarma a las siete de la mañana'),
    jarvis(11, [{ type: 'tool_use', name: 'mcp__life-assistant-telefono__poner_alarma', input: {} }]),
    resultado(12, '{"ok": false, "motivo": "No llego a Home Assistant"}'),
    jarvis(21, [{ type: 'text', text: '🗣️ VOICE_RESPONSE: No he podido ponerla, señor: Home Assistant no responde.' }]),
    usuario(30, AHORA + '[Te ha interrumpido mientras hablabas: puede que no oyera el final de tu respuesta] no, déjalo'),
    jarvis(31, [{ type: 'text', text: '🗣️ VOICE_RESPONSE: ' + new Array(45).fill('bla').join(' ') }]),
    '{"type":"cost-state"}', 'esto no es json',
  ];
}

test('separarPrompt: lo que dijo, sin la cabecera ni los avisos; lo que no es suyo, fuera', function () {
  assert.deepStrictEqual(separarPrompt('[X] cabecera [con] corchetes\n' + AHORA + '[Modo coche: a] [Otro aviso] abre el garaje'),
    { dicho: 'abre el garaje', avisos: ['Modo coche: a', 'Otro aviso'] });
  assert.strictEqual(separarPrompt('Di solo «listo».'), null);
  assert.strictEqual(separarPrompt(AHORA + '[SYSTEM CONTEXT - DO NOT REPEAT]: You just called the user'), null);
});

test('leerSesion: turnos con lo dicho, la voz, las herramientas y lo que tardó', function () {
  const s = leerSesion(llamada(), 'abc12345-0000');
  assert.strictEqual(s.turnos.length, 3);
  assert.strictEqual(s.inicio, '2026-11-09T18:00:00.000Z');
  assert.deepStrictEqual(s.turnos.map(function (t) { return t.dicho; }),
    ['pon una alarma a las siete', 'que pongas una alarma a las siete de la mañana', 'no, déjalo']);
  assert.deepStrictEqual(s.turnos[1].herramientas, ['poner_alarma']);
  assert.strictEqual(s.turnos[1].segundos, 11);
  assert.strictEqual(s.turnos[0].voz, '¿De la mañana o de la tarde, señor?');
});

test('fricciones: repetirse, el fallo, lo lento, el no puedo, el corte, corregir y lo largo', function () {
  const roces = fricciones(leerSesion(llamada(), 'abc'));
  assert.deepStrictEqual(roces.map(function (r) { return r.turno + ':' + r.tipo; }),
    ['2:se_repite', '2:lento', '2:herramienta_fallo', '2:no_puede', '3:corrige', '3:le_corta', '3:largo']);
  assert.strictEqual(resumen(roces).split(', ').length, 7);
  // Un «no» a una pregunta de Jarvis es una respuesta, no una corrección.
  assert.deepStrictEqual(fricciones(leerSesion([usuario(0, AHORA + '¿qué hora es?'),
    jarvis(1, [{ type: 'text', text: '🗣️ VOICE_RESPONSE: Las siete, señor. ¿Le pongo una alarma?' }]),
    usuario(5, AHORA + 'no, no hace falta'),
    jarvis(6, [{ type: 'text', text: '🗣️ VOICE_RESPONSE: Entendido, señor.' }])], 'x')), []);
});

test('parecido: la misma petición con otras palabras se parece; otra petición, no', function () {
  assert.ok(parecido('abre la puerta del garaje', 'Jarvis, que abras la puerta del garaje') < 1);
  assert.ok(parecido('recuérdame a las ocho sacar la basura', 'que me recuerdes a las ocho sacar la basura') >= 0.6);
  assert.ok(parecido('abre el garaje', 'qué tiempo hace mañana') < 0.2);
  assert.strictEqual(parecido('sí', 'sí'), 0);
});

test('casoDe: la llamada queda como caso del simulador, sin esperar nada todavía', function () {
  const s = leerSesion([usuario(0, AHORA + '[Modo coche: a la escucha] enciende la luz')], 'abc12345-9999');
  assert.deepStrictEqual(casoDe(s, [{ tipo: 'lento' }, { tipo: 'lento' }]),
    { id: 'real-2026-11-09-abc12345', de: '2026-11-09T18:00:00.000Z', roces: ['lento'], modo: 'coche',
      turnos: ['enciende la luz'], espera: {} });
});

test('mirar: solo las llamadas recientes y con algún turno; los casos no se repiten', function () {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'repaso-test-'));
  try {
    fs.writeFileSync(path.join(tmp, 'aaaa.jsonl'), llamada().join('\n'));
    fs.writeFileSync(path.join(tmp, 'vacia.jsonl'), usuario(0, 'Di solo «listo».'));
    fs.writeFileSync(path.join(tmp, 'vieja.jsonl'), llamada().join('\n'));
    const hace3dias = new Date(Date.now() - 72 * 3600 * 1000);
    fs.utimesSync(path.join(tmp, 'vieja.jsonl'), hace3dias, hace3dias);
    const llamadas = mirar(tmp, 24);
    assert.deepStrictEqual(llamadas.map(function (l) { return l.sesion.id; }), ['aaaa']);
    const escrita = escribirLlamada(llamadas[0]);
    assert.match(escrita, /2\. Mikel: «que pongas una alarma/);
    assert.match(escrita, /⚠ tuvo que repetirse/);
    const ruta = path.join(tmp, 'casos.json');
    const caso = casoDe(llamadas[0].sesion, llamadas[0].roces);
    assert.strictEqual(guardarCasos(ruta, [caso]), 1);
    assert.strictEqual(guardarCasos(ruta, [caso]), 1);
    assert.throws(function () { mirar(path.join(tmp, 'no-existe'), 24); }, /No puedo leer las sesiones/);
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});
