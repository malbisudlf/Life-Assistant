// Parche 34: node voice-app/test/parche34.test.js (sin tele ni red)
const assert = require('assert');
const { interpretar, interpretarVarias } = require('../lib/reflejos');
const { pareceCompleta } = require('../lib/anticipo');
const tele = require('../lib/tele');

const si = [
  ['Apaga la tele.', { accion: 'apagar' }],
  ['Jarvis, apaga la tele de la sala, por favor.', { accion: 'apagar' }],
  ['¿Puedes apagar la televisión?', { accion: 'apagar' }],
  ['Enciende la tele', { accion: 'encender' }],
  ['Pon la tele.', { accion: 'encender' }],
  ['Sube el volumen.', { accion: 'volumen_subir' }],
  ['Baja el volumen de la tele un poco.', { accion: 'volumen_bajar' }],
  ['Baja la tele.', { accion: 'volumen_bajar' }],
  ['Sube el volumen cinco.', { accion: 'volumen_subir', valor: 5 }],
  ['Baja el volumen 3 puntos.', { accion: 'volumen_bajar', valor: 3 }],
  ['Pon el volumen a 20.', { accion: 'volumen_poner', valor: 20 }],
  ['Pon el volumen de la tele al veinticinco.', { accion: 'volumen_poner', valor: 25 }],
  ['Pon el volumen a treinta y dos', { accion: 'volumen_poner', valor: 32 }],
  ['Silencia la tele', { accion: 'silenciar' }],
  ['Quita el sonido de la tele', { accion: 'silenciar' }],
  ['Quita el silencio', { accion: 'quitar_silencio' }],
  ['Pausa.', { accion: 'pausa' }],
  ['Pausa la película.', { accion: 'pausa' }],
  ['Pon pausa', { accion: 'pausa' }],
  ['Para la tele.', { accion: 'pausa' }],
  ['Reanuda.', { accion: 'reproducir' }],
  ['Dale al play', { accion: 'reproducir' }],
  ['Sigue con la peli', { accion: 'reproducir' }],
  ['Abre Netflix.', { accion: 'abrir', valor: 'netflix' }],
  ['Pon YouTube en la tele.', { accion: 'abrir', valor: 'youtube' }],
  ['Oye, abre la aplicación de Disney', { accion: 'abrir', valor: 'disney' }],
  ['Pon el canal cinco', { accion: 'canal', valor: 5 }],
  ['Enciende la tele y ponme Netflix.', { accion: 'abrir', valor: 'netflix' }],
  ['Abre Prime Video en la tele, porfa.', { accion: 'abrir', valor: 'prime video' }],
];
for (const [dicho, esperado] of si) {
  assert.deepStrictEqual(interpretar(dicho), esperado, dicho);
}

// Lo que NO puede disparar nada: o es de otra cosa, o lleva una condición que hay que pensar.
const no = [
  'Sigue.', 'Para.', 'Siguiente.', 'Sigue leyendo.', 'Atrás.',
  'Apaga la tele cuando acabe la película.',
  'Apaga la luz.', 'Apaga el PC.', 'Pon una alarma a las ocho.',
  'Pon Breaking Bad en la tele.', 'Pon música.', 'Sube la persiana.', 'Baja la persiana.',
  '¿Está encendida la tele?', '¿Qué es Netflix?', 'Cuánto cuesta Netflix',
  'Sube el volumen del PC.', 'Baja el volumen del móvil.', 'Sube la nota del examen.',
  'Max', 'Netflix', 'Pon la lavadora.', 'Mándale a Erik que apague la tele.',
];
for (const dicho of no) {
  assert.strictEqual(interpretar(dicho), null, dicho);
}

// La casa
const casa = function (d) { const o = interpretar(d); return o && o.casa; };
assert.deepStrictEqual(casa('Apaga el jardín.'), { servicio: 'switch.turn_off', entidad: 'switch.luces_jardin' });
assert.deepStrictEqual(casa('Enciende las luces del jardín, por favor.'), { servicio: 'switch.turn_on', entidad: 'switch.luces_jardin' });
assert.deepStrictEqual(casa('Apaga mi luz'), { servicio: 'light.turn_off', entidad: 'light.luces_mesa' });
assert.deepStrictEqual(casa('Pon la calefacción de la cocina a 21.'), { servicio: 'climate.set_temperature', entidad: 'climate.cocina', datos: { temperature: 21 } });
assert.deepStrictEqual(casa('Pon mi cuarto a veintidós grados'), { servicio: 'climate.set_temperature', entidad: 'climate.hab_mikel', datos: { temperature: 22 } });
assert.deepStrictEqual(casa('Baja la calefacción de mi cuarto a 19 grados'), { servicio: 'climate.set_temperature', entidad: 'climate.hab_mikel', datos: { temperature: 19 } });
assert.strictEqual(interpretar('Pon la calefacción de la cocina a 30'), null);   // fuera de rango: Claude
assert.strictEqual(interpretar('Pon la calefacción a 21'), null);                 // sin zona: Claude
assert.strictEqual(interpretar('Pon el cuarto de Marco a 21'), null);             // el de otro: Claude
assert.strictEqual(interpretar('Abre el garaje'), null);
assert.strictEqual(interpretar('Quita la alarma'), null);
assert.strictEqual(interpretar('Apaga la luz'), null);                            // ¿cuál?
assert.strictEqual(interpretar('Apaga el jardín cuando anochezca'), null);
assert.deepStrictEqual(interpretarVarias('Apaga el jardín y baja el volumen.').map(function (o) { return !!o.casa; }), [true, false]);

// Varias a la vez: todas o ninguna
assert.deepStrictEqual(interpretarVarias('Puedes, por ejemplo, baja el volumen dos niveles y abre Jellyfin.'), null);
assert.deepStrictEqual(interpretarVarias('Baja el volumen dos niveles y abre Jellyfin.'),
  [{ accion: 'volumen_bajar', valor: 2 }, { accion: 'abrir', valor: 'jellyfin' }]);
assert.deepStrictEqual(interpretarVarias('Apaga la tele.'), [{ accion: 'apagar' }]);
assert.strictEqual(interpretarVarias('Abre Netflix y ponme El mentalista otra vez.'), null);
assert.strictEqual(interpretarVarias('Apaga la tele y llama a Erik.'), null);
assert.strictEqual(interpretarVarias('Apaga la luz y la tele.'), null);

// El cierre rápido de la frase
for (const t of ['Apaga la tele.', '¿Qué tiempo hace?', 'Vale.', 'Llámame a las ocho.']) {
  assert.strictEqual(pareceCompleta(t), true, t);
}
for (const t of ['', 'Quiero que.', 'Mándale un mensaje a', 'Dile que y...', 'Pregúntale si,', 'Eh.', 'Mañana tengo que ir a la.', 'Pues']) {
  assert.strictEqual(pareceCompleta(t), false, t);
}

// Encontrar la aplicación por lo que se dice
const instaladas = [
  { id: '1', nombre: 'Netflix', tipo: 2 }, { id: '2', nombre: 'Prime Video', tipo: 2 },
  { id: '3', nombre: 'Disney+', tipo: 2 }, { id: '4', nombre: 'YouTube', tipo: 4 },
  { id: '5', nombre: 'Jellyfin', tipo: 4 }, { id: '6', nombre: 'Max', tipo: 2 },
];
const encuentra = function (d) { const a = tele.buscarApp(instaladas, d); return a && a.id; };
assert.strictEqual(encuentra('netflix'), '1');
assert.strictEqual(encuentra('prime'), '2');
assert.strictEqual(encuentra('amazon'), '2');
assert.strictEqual(encuentra('disney'), '3');
assert.strictEqual(encuentra('you tube'), '4');
assert.strictEqual(encuentra('hbo'), '6');
assert.strictEqual(tele.buscarApp([{ id: '9', nombre: 'HBO Max', tipo: 2 }], 'max').id, '9');
assert.strictEqual(encuentra('tiktok'), null);
assert.strictEqual(tele.buscarApp([], 'netflix').id, '3201907018807');

console.log('parche 34: todo bien');
