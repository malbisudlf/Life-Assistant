// Parche 40: «pon el tablero» abre la app «Jarvis» de la tele (tele/tablero-tizen/ en Life Assistant).
const test = require('node:test');
const assert = require('node:assert');
const tele = require('../lib/tele');
const { interpretar } = require('../lib/reflejos');

test('p40: el tablero es una app conocida, y sus nombres van a ella', () => {
  for (const dicho of ['tablero', 'el tablero', 'dashboard', 'Jarvis']) {
    assert.ok(tele.esAppConocida(dicho), dicho);
  }
});

test('p40: «pon el tablero» y «enciende la tele y pon el tablero» abren la app', () => {
  const a = interpretar('Pon el tablero.');
  assert.ok(a && JSON.stringify(a).includes('abrir') && JSON.stringify(a).includes('tablero'), JSON.stringify(a));
  const b = interpretar('Enciende la tele y pon el tablero.');
  assert.ok(b && JSON.stringify(b).includes('tablero'), JSON.stringify(b));
});
