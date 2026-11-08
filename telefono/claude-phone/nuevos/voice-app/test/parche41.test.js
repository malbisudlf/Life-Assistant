// Parche 41: una app conocida que falta en la lista (la tele no contestó a tiempo) se pregunta sola.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');

test('p41: «abrir» pregunta por la conocida suelta antes de decir que no está', () => {
  const fuente = fs.readFileSync(require.resolve('../lib/tele'), 'utf8');
  assert.match(fuente, /if \(!app\) app = await appConocidaSuelta\(dicho\);/);
  assert.match(fuente, /async function appConocidaSuelta\(dicho\)/);
  assert.match(fuente, /estadoApp\(id, 6000\)/);
});
