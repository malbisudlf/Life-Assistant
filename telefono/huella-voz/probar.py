"""Prueba de punta a punta del servicio de la huella, como la haría la voice-app.

Graba dos perfiles de un mismo hablante de LibriSpeech por el canal simulado de banco.py:
`prueba-altavoz` (el canal a pelo) y `prueba-coche` (con el ruido de coche de banco.py).
Luego le pregunta por frases suyas, limpias y con ruido, y de los otros 39, dice con qué
perfil coincidió cada una y al acabar BORRA los dos perfiles: no deja nada grabado.
Necesita el directorio del banco (LibriSpeech/) y el servicio en marcha, con la llave en
HUELLA_TOKEN. Con BANCO_RAPL (la URL de un node-exporter con rapl), los julios.

    HUELLA_TOKEN=… python probar.py http://<jacobo>:8771 [hablante]
"""
import collections, glob, json, os, re, statistics, sys, time, urllib.request
import numpy as np
import soundfile as sf

sys.argv += [] if len(sys.argv) > 1 else ['http://127.0.0.1:8771']
URL, TOKEN = sys.argv[1].rstrip('/'), os.environ['HUELLA_TOKEN']
RAPL = os.getenv('BANCO_RAPL', '')
rng = np.random.default_rng(3)


def telefono(x, snr=None):
    # El mismo canal que banco.py: ruido marrón opcional, 300-3.400 Hz y G.711 μ-law
    if snr is not None:
        r = np.cumsum(rng.normal(0, 1, len(x)))
        r -= np.convolve(r, np.ones(801) / 801, 'same')
        r *= np.sqrt(np.mean(x ** 2) / np.mean(r ** 2) / 10 ** (snr / 10))
        x = x + r
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1 / 16000)
    X[(f < 300) | (f > 3400)] = 0
    y = np.clip(np.fft.irfft(X, len(x)), -1, 1)
    mu = 255
    c = np.round(np.sign(y) * np.log1p(mu * np.abs(y)) / np.log1p(mu) * 127) / 127
    return (np.sign(c) * ((1 + mu) ** np.abs(c) - 1) / mu).astype(np.float32)


def pcm(x):
    return (np.clip(x, -1, 1) * 32767).astype('<i2').tobytes()


def pide(ruta, cuerpo=None, cabeceras=None, metodo=None):
    r = urllib.request.Request(URL + ruta, cuerpo, dict({'X-Auth-Token': TOKEN}, **(cabeceras or {})),
                               method=metodo)
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
for perfil, snr in (('prueba-altavoz', None), ('prueba-coche', 10)):
    alta, t = [], 0
    while t < 30:
        x, _ = sf.read(suyas.pop(), dtype='float32'); x = x[:5 * 16000]
        alta.append(pcm(telefono(x, snr))); t += len(x) / 16000
    print('alta', perfil, pide('/alta', b''.join(alta), {'X-Frases': ','.join(str(len(a)) for a in alta),
                                                         'X-Perfil': perfil}))


def prueba(ruta, snr=None):
    x, _ = sf.read(ruta, dtype='float32')
    return pcm(telefono(x[: int(rng.uniform(1.5, 4) * 16000)], snr))

casos = [('suya, limpia', True, prueba(p)) for p in suyas[:12]]
casos += [('suya, coche', True, prueba(p, 10)) for p in suyas[12:24]]
casos += [('de otros', False, prueba(frases(h)[0], rng.choice([None, 10]))) for h in hablantes if h != el]
j0, ms, por_tipo = julios(), [], collections.defaultdict(list)
for tipo, es_el, audio in casos:
    t0 = time.time(); codigo, r = pide('/verificar', audio); ms.append((time.time() - t0) * 1000)
    por_tipo[tipo].append((r['es_el'] == es_el, r['similitud'], r['perfil'] if r['es_el'] else '-'))
j = julios()
for tipo, rs in por_tipo.items():
    print(f'{tipo:13} {sum(b for b, _, _ in rs)}/{len(rs)} bien, similitud mediana '
          f'{statistics.median(s for _, s, _ in rs):.2f}, aceptadas por: {dict(collections.Counter(p for *_, p in rs))}')
print(f'{statistics.median(ms):.0f} ms por petición (p95 {sorted(ms)[int(len(ms) * .95)]:.0f})'
      + (f', {(j - j0) / len(casos):.2f} J/petición' if j0 is not None else ''))
print('salud:', pide('/salud')[1])
for perfil in ('prueba-altavoz', 'prueba-coche'):
    print('borrado', perfil, pide('/perfil/' + perfil, metodo='DELETE'))
print('al acabar:', pide('/salud')[1]['perfiles'])
