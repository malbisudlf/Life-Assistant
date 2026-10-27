// Uso, en caja: node telefono/medir-primer-turno.js frio|proceso|entero (parche 27, telefono/PARCHES.md).
// Primer turno de una llamada: en frío (hoy), con solo el proceso arrancado antes, y
// con el preámbulo ya mandado (precalentado entero). Usa los módulos del puente.
process.chdir(process.env.HOME + '/telefono-jarvis');
const D = process.env.HOME + '/.claude-phone-cli/claude-api-server/';
const sesionViva = require(D + 'sesion-viva');
const contexto = require(D + 'contexto');
const { randomUUID } = require('crypto');
const env = Object.assign({}, process.env, { ENABLE_CLAUDEAI_MCP_SERVERS: 'false', CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: '1' });
const espera = (ms) => new Promise((r) => setTimeout(r, ms));
const DEVICE = require(process.env.HOME + '/.claude-phone-cli/voice-app/config/devices.json')['11411'].prompt;
const VOZ = '[VOICE CALL CONTEXT]\nThis query comes via voice call. Include 🗣️ VOICE_RESPONSE: (40 words max) and 🎯 COMPLETED: (12 words max).\n[END VOICE CONTEXT]\n\n';
const PREG = '¿Qué tengo mañana por la mañana?';
function nueva() {
  const id = randomUUID();
  const args = ['--dangerously-skip-permissions', '-p', '--input-format', 'stream-json', '--output-format', 'stream-json', '--verbose', '--model', 'claude-sonnet-5-5', '--session-id', id];
  return sesionViva.crear({ args, env, bin: process.env.HOME + '/.local/bin/claude' });
}
const cabeza = () => `[DEVICE IDENTITY]\n${DEVICE}\n[END DEVICE IDENTITY]\n\n` + VOZ;
(async () => {
  const modo = process.argv[2];
  const s = nueva();
  let t;
  if (modo === 'frio') {
    t = Date.now();
    const ctx = await contexto.pedir();
    const rr = await s.preguntar(cabeza() + ctx + PREG); console.log("  >", rr.isError, rr.response.slice(0,150));
  } else if (modo === 'proceso') {
    const ctx = contexto.pedir();
    await espera(6000);
    t = Date.now();
    const rr = await s.preguntar(cabeza() + (await ctx) + PREG); console.log("  >", rr.isError, rr.response.slice(0,150));
  } else {
    const t0 = Date.now();
    const ctx = await contexto.pedir();
    await s.preguntar(cabeza() + ctx + '[Acaba de descolgar y aún no ha dicho nada. No contestes a esto: responde solo «listo».]');
    const calentado = Date.now() - t0;
    await espera(Math.max(0, 6000 - calentado));
    t = Date.now();
    const rr = await s.preguntar(cabeza() + PREG); console.log("  >", rr.isError, rr.response.slice(0,150));
    console.log('  (precalentado en ' + calentado + ' ms)');
  }
  console.log(modo.padEnd(8), (Date.now() - t) + ' ms hasta la respuesta a la pregunta');
  s.cerrar();
  await espera(500);
  process.exit(0);
})().catch((e) => { console.error('FALLO', e.message); process.exit(1); });
