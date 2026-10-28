"""Prueba de punta a punta del servicio de la huella, como la haría la voice-app.

Graba la huella de un hablante de LibriSpeech por el canal simulado de banco.py y luego
le pregunta por frases suyas y de otros. Necesita el directorio del banco (LibriSpeech/) y
el servicio en marcha; la llave, en HUELLA_TOKEN. OJO: deja grabada la huella de ese
hablante: bórrala después (datos/huella.json) o graba la buena.

    HUELLA_TOKEN=… python probar.py http://<jacobo>:8771 [hablante]
"""
import glob, json, os, re, statistics, sys, time, urllib.request
import numpy as np
import soundfile as sf

sys.argv += [] if len(sys.argv) > 1 else ['http://127.0.0.1:8771']
URL, TOKEN = sys.argv[1].rstrip('/'), os.environ['HUELLA_TOKEN']
RAPL = os.getenv('BANCO_RAPL', '')
rng = np.random.default_rng(3)


def telefono(x):
    # El mismo canal que banco.py: 300-3.400 Hz y G.711 μ-law
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1 / 16000)
    X[(f < 300) | (f > 3400)] = 0
    y = np.clip(np.fft.irfft(X, len(x)), -1, 1)
    mu = 255
    c = np.round(np.sign(y) * np.log1p(mu * np.abs(y)) / np.log1p(mu) * 127) / 127
    return (np.sign(c) * ((1 + mu) ** np.abs(c) - 1) / mu).astype(np.float32)


def pcm(x):
    return (np.clip(x, -1, 1) * 32767).astype('<i2').tobytes()


def pide(ruta, cuerpo, cabeceras=None):
    r = urllib.request.Request(URL + ruta, cuerpo, dict({'X-Auth-Token': TOKEN}, **(cabeceras or {})))
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def julios():
    if not RAPL:
        return None
    t = urllib.request.urlopen(RAPL, timeout=5).read().decode()
    return sum(float(m) for m in re.findall(r'^node_rapl_package_joules_total\{[^}]*\} (\S+)', t, re.M))


hablantes = sorted(os.listdir('LibriSpeech/test-clean'))
el = sys.argv[2] if len(sys.argv) > 2 else hablantes[0]
def frases(h):
    fs = sorted(glob.glob(f'LibriSpeech/test-clean/{h}/*/*.flac')); rng.shuffle(fs); return fs

suyas = frases(el)
alta, t = [], 0
while t < 30:
    x, _ = sf.read(suyas.pop(), dtype='float32'); x = x[:5 * 16000]; alta.append(pcm(telefono(x))); t += len(x) / 16000
print('alta:', pide('/alta', b''.join(alta), {'X-Frases': ','.join(str(len(a)) for a in alta)}))

def prueba(ruta):
    x, _ = sf.read(ruta, dtype='float32')
    return pcm(telefono(x[: int(rng.uniform(1.5, 4) * 16000)]))

casos = [(True, prueba(p)) for p in suyas[:12]]
casos += [(False, prueba(frases(h)[0])) for h in hablantes if h != el]
j0, aciertos, ms, sims = julios(), 0, [], {True: [], False: []}
for es_el, audio in casos:
    t0 = time.time(); codigo, r = pide('/verificar', audio); ms.append((time.time() - t0) * 1000)
    aciertos += r['es_el'] == es_el; sims[es_el].append(r['similitud'])
j = julios()
print(f'{aciertos}/{len(casos)} bien; similitud suya {statistics.median(sims[True]):.2f} '
      f'(min {min(sims[True]):.2f}), de otros {statistics.median(sims[False]):.2f} (max {max(sims[False]):.2f}); '
      f'{statistics.median(ms):.0f} ms por petición (p95 {sorted(ms)[int(len(ms) * .95)]:.0f})'
      + (f'; {(j - j0) / len(casos):.2f} J/petición' if j0 is not None else ''))
print('salud:', pide('/salud', None)[1])
