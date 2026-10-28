"""Banco de modelos de huella con LibriSpeech test-clean (40 hablantes) por un canal
telefónico simulado (300-3400 Hz, G.711 mu-law) y ruido de coche (marrón, SNR 10 dB).

De aquí salen el modelo y el umbral de partida del parche 23 (ver «El parche 23, en
espera» en telefono/PARCHES.md). Por hablante: ~30 s de alta en frases de hasta 5 s, y 12
pruebas de 1,5-4 s, que es lo que dura un «Jarvis, …». Dos formas de puntuar: el coseno a
pelo, y restando antes la media de los DEMÁS hablantes por el mismo canal («la media del
canal»), que es lo que más ayuda.

    # en un directorio con LibriSpeech/test-clean/ (openslr.org/resources/12) y los .onnx
    # de github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models
    docker run --rm -v $PWD:/w -w /w python:3.12-slim sh -c \\
      "pip install -q sherpa-onnx==2.0.0 numpy soundfile && python banco.py modelo1.onnx ..."

Además deja, por modelo, `media-<modelo>.npy`: la media de las altas de los 40 hablantes
por el canal, que es la que resta servidor.py (HUELLA_MEDIA) en producción. Con
BANCO_HILOS se elige cuántos hilos (servidor.py usa 2), y con BANCO_RAPL la URL de un
node-exporter con el colector rapl: entonces dice también los julios de CPU por frase.
"""
import glob, os, re, sys, time, urllib.request
import numpy as np
import soundfile as sf
import sherpa_onnx

HILOS = int(os.getenv('BANCO_HILOS', '4'))
RAPL = os.getenv('BANCO_RAPL', '')

def julios():
    if not RAPL:
        return None
    texto = urllib.request.urlopen(RAPL, timeout=5).read().decode()
    return sum(float(m) for m in re.findall(r'^node_rapl_package_joules_total\{[^}]*\} (\S+)', texto, re.M))

rng = np.random.default_rng(7)

def telefono(x, snr=None):
    if snr is not None:
        r = np.cumsum(rng.normal(0, 1, len(x)))          # marrón: grave, como un coche
        r -= np.convolve(r, np.ones(801) / 801, 'same')  # sin la deriva
        r *= np.sqrt(np.mean(x ** 2) / np.mean(r ** 2) / 10 ** (snr / 10))
        x = x + r
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1 / 16000)
    X[(f < 300) | (f > 3400)] = 0
    y = np.clip(np.fft.irfft(X, len(x)), -1, 1)
    mu = 255
    c = np.round(np.sign(y) * np.log1p(mu * np.abs(y)) / np.log1p(mu) * 127) / 127
    return (np.sign(c) * ((1 + mu) ** np.abs(c) - 1) / mu).astype(np.float32)

hablantes = sorted(os.listdir('LibriSpeech/test-clean'))
datos = {}
for h in hablantes:
    fs = sorted(glob.glob(f'LibriSpeech/test-clean/{h}/*/*.flac'))
    rng.shuffle(fs)
    alta, t = [], 0
    while t < 30 and fs:
        x, _ = sf.read(fs.pop(), dtype='float32'); x = x[:5 * 16000]; alta.append(x); t += len(x) / 16000
    pruebas = []
    for p in fs[:12]:
        x, _ = sf.read(p, dtype='float32')
        pruebas.append(x[: int(rng.uniform(1.5, 4) * 16000)])
    datos[h] = (alta, pruebas)

def eer(mismo, otro):
    mismo, otro = np.array(mismo), np.array(otro)
    ts = np.sort(np.concatenate([mismo, otro]))
    frr = np.array([(mismo < t).mean() for t in ts]); far = np.array([(otro >= t).mean() for t in ts])
    i = np.argmin(np.abs(frr - far))
    def a_far(objetivo):
        ok = np.where(far <= objetivo)[0][0]
        return frr[ok], ts[ok]
    return (frr[i] + far[i]) / 2, ts[i], a_far(0.01), a_far(0.05)

modelos = sys.argv[1:]
for modelo in modelos:
    ex = sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=modelo, num_threads=HILOS))
    def emb(x):
        s = ex.create_stream(); s.accept_waveform(16000, x); s.input_finished()
        e = np.array(ex.compute(s)); return e / np.linalg.norm(e)
    # El canal se simula antes de cronometrar: lo que se mide es solo el modelo.
    tel = {h: ([telefono(x) for x in alta], [telefono(x) for x in pruebas],
               [telefono(x, snr=10) for x in pruebas]) for h, (alta, pruebas) in datos.items()}
    j0 = julios(); t0 = time.time(); n = 0; segs = 0
    E = {}
    for h, grupos in tel.items():
        E[h] = tuple(np.array([emb(x) for x in g]) for g in grupos)
        n += sum(len(g) for g in grupos); segs += sum(len(x) for g in grupos for x in g) / 16000
    t = time.time() - t0
    gasto = ''
    if j0 is not None:
        j = julios() - j0
        gasto = f'  {j / n:.2f} J/frase, CPU a {j / t:.0f} W de media'
    print(f'\n== {os.path.basename(modelo)}  {t / n * 1000:.0f} ms/frase ({segs / n:.1f} s de audio, '
          f'{HILOS} hilos){gasto}', flush=True)
    np.save(f'media-{os.path.splitext(os.path.basename(modelo))[0]}.npy',
            np.mean(np.concatenate([E[h][0] for h in hablantes]), axis=0).astype(np.float32))
    for norma in ('coseno', 'menos-media'):
        for cual, nombre in ((1, 'tel'), (2, 'tel+coche')):
            mismo, otro = [], []
            for h in hablantes:
                ea = E[h][0]
                if norma == 'menos-media':
                    mu = np.mean(np.concatenate([E[o][0] for o in hablantes if o != h]), axis=0)
                else:
                    mu = 0
                c = np.mean(ea - mu, axis=0); c /= np.linalg.norm(c)
                for o in hablantes:
                    v = E[o][cual] - mu
                    v = v / np.linalg.norm(v, axis=1, keepdims=True)
                    (mismo if o == h else otro).extend((v @ c).tolist())
            e, te, (f1, t1), (f5, t5) = eer(mismo, otro)
            print(f'  {norma:11} {nombre:9} EER {e*100:4.1f}% (umbral {te:.2f}) | FAR 1%: FRR {f1*100:4.1f}% umbral {t1:.2f}'
                  f' | FAR 5%: FRR {f5*100:4.1f}% umbral {t5:.2f} | mismo med {np.median(mismo):.2f} otro med {np.median(otro):.2f}',
                  flush=True)
