<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

## La investigación de noche

Del 2026-11-20, idea de Mikel. «Jarvis, investiga el mejor portátil por 1.500 €» y por la
mañana le llega por Telegram un informe en Markdown: la conclusión en una frase, la
recomendación (y una alternativa), lo que se ha mirado con cifras y fechas, lo que puede
cambiar la decisión, y las fuentes con enlace.

| Pieza | Dónde |
|---|---|
| Quien investiga | `chat/jarvis_claude.py`, el servicio del chat en `caja` («La investigación de noche»): una sesión de Claude Code con **solo WebSearch y WebFetch** |
| El encargo y el informe | `~/jarvis-chat/investigaciones/<id>.json` en `caja` (700/600), 60 días |
| Encargar, listar, leer | herramientas `investigar` e `investigaciones` del backend |
| Entregar | el tick de HA (`_investigar_lanzar`, cada `INVESTIGAR_CADA_MIN`): por Telegram, con el `.md` adjunto, desde `INVESTIGAR_AVISO_DESDE` |

### Lo que no se relaja

1. **La sesión que investiga solo tiene web**: `--tools WebSearch,WebFetch`, sin terminal,
   sin ficheros y sin un solo servidor MCP (`--strict-mcp-config` sin `--mcp-config`). Lee
   páginas de cualquiera; lo peor que puede hacer una que intente darle órdenes es torcer el
   informe. Lo comprueba `tests/backend/test_investigar.py`.
2. **El informe es ajeno** (`investigaciones` está en `_HERRAMIENTAS_AJENAS`): Jarvis lo
   resume como dato, nunca lo ejecuta.
3. **De madrugada** (`JARVIS_INVESTIGAR_DESDE`..`HASTA`, por defecto 01-07 en la hora de
   caja), de una en una, con Opus y esfuerzo alto: gasta límite de la suscripción cuando no
   estorba. Con `ya` empieza al momento y se entrega al acabar.
4. **Encargar no se confirma**: no cambia nada ni le habla a nadie.

### Ponerlo en marcha

1. Copiar `chat/jarvis_claude.py` a `~/jarvis-chat/` en caja y reiniciar el servicio
   (`systemctl --user restart jarvis-claude`). Con el viejo, `investigar` dice que falta.
2. Nada en el backend: usa `JARVIS_CLAUDE_URL` y `JARVIS_CLAUDE_TOKEN`, los del chat.
3. Probar: «Jarvis, investiga ya qué freidora de aire me compro por menos de 150 €».
