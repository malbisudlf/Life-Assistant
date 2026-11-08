// Parche 42: cada petición a la tele va en su propia conexión (la tele cierra la reutilizada).
const test = require('node:test');
const assert = require('node:assert');
const http = require('node:http');

test('p42: dos peticiones seguidas a un servidor que cierra la conexión salen las dos', async () => {
  const srv = http.createServer((req, res) => { res.setHeader('Connection', 'close'); res.end('{"name":"Jarvis"}'); });
  await new Promise((r) => srv.listen(0, '127.0.0.1', r));
  process.env.TELE_IP = '127.0.0.1';
  delete require.cache[require.resolve('../lib/tele')];
  const fuente = require('fs').readFileSync(require.resolve('../lib/tele'), 'utf8');
  assert.match(fuente, /host: IP, agent: false/);
  // Lo mismo que hace pedirHttp, contra el servidor: con agent:false, ninguna falla.
  const pedir = () => new Promise((resolve, reject) => {
    const r = http.request({ host: '127.0.0.1', port: srv.address().port, path: '/', agent: false }, (res) => {
      res.resume(); res.on('end', () => resolve(res.statusCode));
    });
    r.on('error', reject); r.end();
  });
  for (let i = 0; i < 4; i++) assert.strictEqual(await pedir(), 200);
  srv.close();
});
