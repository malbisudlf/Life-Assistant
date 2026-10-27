"""Prueba el oído de punta a punta como lo usará la voice-app: manda un WAV por el
WebSocket a su ritmo real (trozos de 20 ms), enseña los parciales según llegan y pide el
final al acabar. Mide cuánto tarda el final desde que se dice «fin».

Uso: OIDO_TOKEN=… python probar.py <url> <fichero.wav> [<fichero.wav> …]
     (url: ws://jacobo:8770/escucha). Necesita aiohttp.
"""

import asyncio
import json
import os
import sys
import time
import wave

from aiohttp import ClientSession


async def una_frase(ws, ruta):
    with wave.open(ruta) as w:
        hz, pcm = w.getframerate(), w.readframes(w.getnframes())
    trozo = hz * 2 // 50                          # 20 ms
    t0 = time.perf_counter()

    async def lee():
        async for msg in ws:
            m = json.loads(msg.data)
            t = time.perf_counter() - t0
            if m["tipo"] == "parcial":
                print(f"  {t:5.2f} s  [{m['ms']:4d} ms] {m['fijo']} | {m['provisional']}"
                      + (f"  ← Jarvis ({m['nombre']})" if m["nombre"] else ""))
            else:
                return m

    lector = asyncio.create_task(lee())
    for i in range(0, len(pcm), trozo):
        await ws.send_bytes(pcm[i:i + trozo])
        # A su ritmo real, contando desde el principio para no acumular retraso
        await asyncio.sleep(max(0, t0 + (i + trozo) / (hz * 2) - time.perf_counter()))
    t_fin = time.perf_counter()
    await ws.send_str(json.dumps({"tipo": "fin"}))
    final = await lector
    print(f"  FINAL a los {(time.perf_counter() - t_fin) * 1000:.0f} ms de acabar "
          f"(Whisper {final.get('ms')} ms): {final.get('texto')!r}")


async def main(url, rutas):
    with wave.open(rutas[0]) as w:
        hz = w.getframerate()
    cabeceras = {"X-Auth-Token": os.environ["OIDO_TOKEN"]}
    async with ClientSession() as s:
        async with s.ws_connect(f"{url}?hz={hz}", headers=cabeceras) as ws:
            for r in rutas:
                print(os.path.basename(r))
                await una_frase(ws, r)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2:]))
