"""Carga de jacobo como la tendría el oído, para medir ventilador y temperaturas (2026-10-27).
  llamada:  hablas ~4 s (small cada 0,5 s sobre lo dicho), turbo una vez al acabar,
            y ~6 s callado mientras contesta Jarvis
  coche:    escucha pasiva con la radio hablando sin parar: small cada 0,5 s sobre los
            últimos 3 s, todo el rato, sin turbo
  reposo:   nada
Uso: carga.py <escenario> <segundos>. Muestrea cada 2 s y escribe resultados/carga-<escenario>.tsv"""
import sys, time, threading, pathlib, wave, io, statistics
import requests

escenario, duracion = sys.argv[1], float(sys.argv[2])
DATOS = pathlib.Path.home() / "oido/datos/mls/tel"
RES = pathlib.Path.home() / "oido/banco/resultados"
amd = next(p.parent for p in pathlib.Path("/sys/class/hwmon").glob("*/name") if p.read_text().strip() == "amdgpu")
core = next(p.parent for p in pathlib.Path("/sys/class/hwmon").glob("*/name") if p.read_text().strip() == "coretemp")
busy = pathlib.Path("/sys/class/drm/card1/device/gpu_busy_percent")
lee = lambda p: int(p.read_text())

pcm = b"".join(wave.open(str(f)).readframes(10**9) for f in sorted(DATOS.glob("*.wav"))[:20])
def trozo(ini, seg):
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        a = int(ini * 32000) % (len(pcm) - int(seg * 32000))
        w.writeframes(pcm[a:a + int(seg * 32000)])
    return b.getvalue()
def pide(puerto, wav):
    requests.post(f"http://127.0.0.1:{puerto}/inference", files={"file": ("a.wav", wav)},
                  data={"language": "es", "response_format": "json", "temperature": "0"}, timeout=60)

muestras, fin = [], time.time() + duracion
def muestrea():
    while time.time() < fin:
        muestras.append((time.time(), lee(amd / "pwm1") * 100 / 255, lee(amd / "temp1_input") / 1000,
                         lee(amd / "power1_input") / 1e6, lee(busy),
                         max(lee(t) for t in core.glob("temp*_input")) / 1000))
        time.sleep(2)
hilo = threading.Thread(target=muestrea); hilo.start()

t = 0.0
while time.time() < fin:
    if escenario == "coche":
        t0 = time.time(); pide(8091, trozo(t, 3)); t += 0.5
        time.sleep(max(0, 0.5 - (time.time() - t0)))
    elif escenario == "llamada":
        for k in range(1, 9):                      # 4 s hablando
            t0 = time.time(); pide(8091, trozo(t, k * 0.5))
            time.sleep(max(0, 0.5 - (time.time() - t0)))
        pide(8090, trozo(t, 4)); t += 4            # fin de frase: turbo
        time.sleep(6)                              # contesta Jarvis
    else:
        time.sleep(1)
hilo.join()

with open(RES / f"carga-{escenario}.tsv", "w") as f:
    for m in muestras:
        f.write("\t".join(f"{x:.1f}" for x in m) + "\n")
col = lambda i: [m[i] for m in muestras]
fan, tg, pw, ocu, tc = (col(i) for i in range(1, 6))
print(f"{escenario}\tventilador GPU {min(fan):.0f}-{max(fan):.0f} % (último {fan[-1]:.0f} %)"
      f"\tGPU {max(tg):.0f} °C máx\t{statistics.mean(pw):.0f} W medios, {max(pw):.0f} máx"
      f"\tocupación GPU {statistics.mean(ocu):.0f} %\tCPU {max(tc):.0f} °C máx")
