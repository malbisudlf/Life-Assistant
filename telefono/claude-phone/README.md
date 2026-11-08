# claude-phone, tal como corre en caja

Hasta el 2026-11-08 los parches de claude-phone vivían de verdad solo en `caja`: aquí había
un `parche-NN.diff` por parche, pero no todos (el 13, el 23, el 33 o el 34 a medias), y
nada garantizaba que la suma de los diffs fuera lo que corre. Un `claude-phone update`
se llevaba los cambios, y rehacerlos a partir de los diffs era arqueología.

Este directorio es **la foto entera** de lo que corre, sacada de `caja` con un script:

| Fichero | Qué es |
|---|---|
| `BASE` | El commit del repositorio original (theNetworkChuck/claude-phone) sobre el que va todo |
| `cambios.diff` | Lo que está tocado de los ficheros del original (`git diff` contra `BASE`) |
| `nuevos/` | Lo que es nuestro: módulos (`anticipo.js`, `tele.js`, `sesion-viva.js`…) y sus tests |
| `compose.yml` | `~/.claude-phone/docker-compose.yml` (parches 13 y 33), con `${EXTERNAL_IP}` y `${HOME}` en vez de la IP de la LAN y la ruta de usuario |
| `exportar.sh` | Saca la foto de `caja`. Se niega si encuentra una IP privada, una ruta de usuario o algo con forma de clave |
| `aplicar.sh` | Monta claude-phone desde la foto: en un directorio nuevo (lo normal, para pasar los tests) o `--en-sitio` |
| `comprobar.sh` | Compara `caja` con la foto. Si no coinciden, alguien tocó `caja` sin versionarlo |

**Lo que no está, a propósito:** `config/devices.json` y `config/tele-token.json`
(credenciales), `~/.claude-phone/.env`, las frases fijas (se regeneran al arrancar),
`static/hold-music.wav` y los `.bak-*`.

## Cómo se trabaja ahora

1. Cambias la voice-app o el puente (en una copia, como siempre: `/tmp/pNN` en caja).
2. Lo aplicas en caja con su imagen de vuelta atrás (`antes-pNN`), como hasta ahora.
3. **Sacas la foto y la commiteas en el mismo cambio que el `parche-NN.diff`**:
   ```bash
   ssh caja 'bash -s' < telefono/claude-phone/exportar.sh > /tmp/cp.tar
   tar -xf /tmp/cp.tar -C telefono/claude-phone
   ```
4. `bash telefono/claude-phone/comprobar.sh` tiene que decir que coinciden.

Los `parche-NN.diff` sueltos se quedan: cuentan **por qué** entró cada cosa y en qué orden.
La foto cuenta **qué** hay. Si discrepan, manda la foto.

## Si un `claude-phone update` se lleva los cambios

```bash
cd ~ && bash <ruta>/telefono/claude-phone/aplicar.sh /tmp/cp-nuevo
cd /tmp/cp-nuevo/voice-app && npm ci && node --test test/
```

Si los tests pasan, se copia sobre `~/.claude-phone-cli` (o se usa `--en-sitio`, que guarda
copia de lo que pisa) y se reconstruye la voice-app. Si el original ha cambiado tanto que
`cambios.diff` no entra, toca rehacerlo a mano: `BASE` dice desde dónde.
