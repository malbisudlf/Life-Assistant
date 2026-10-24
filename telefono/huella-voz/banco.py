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
"""
import glob, os, sys, time
import numpy as np
import soundfile as sf
import sherpa_onnx

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
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=modelo, num_threads=4))
    def emb(x):
        s = ex.create_stream(); s.accept_waveform(16000, x); s.input_finished()
        e = np.array(ex.compute(s)); return e / np.linalg.norm(e)
    t0 = time.time(); n = 0
    E = {}
    for h, (alta, pruebas) in datos.items():
        ea = [emb(telefono(x)) for x in alta]
        ep = [emb(telefono(x)) for x in pruebas]
        er = [emb(telefono(x, snr=10)) for x in pruebas]
        n += len(ea) + 2 * len(ep)
        E[h] = (np.array(ea), np.array(ep), np.array(er))
    print(f'\n== {os.path.basename(modelo)}  {(time.time() - t0) / n * 1000:.0f} ms/frase', flush=True)
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
