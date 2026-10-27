"""Banco de Whisper en jacobo (2026-10-27): tiempo y WER sobre frases en español por el
canal del teléfono. Dos motores:
  cpp:<url>        un whisper-server de whisper.cpp ya levantado (Vulkan o CPU)
  fw:<modelo>      faster-whisper en CPU, int8
Uso: python banco_whisper.py <etiqueta> <motor> [hilos]
Escribe una línea por frase en resultados/<etiqueta>.tsv y un resumen por pantalla."""
import sys, time, pathlib, re, statistics, unicodedata
import jiwer, requests

DATOS = pathlib.Path.home() / "oido/datos/mls"
RES = pathlib.Path.home() / "oido/banco/resultados"
RES.mkdir(exist_ok=True)
etiqueta, motor = sys.argv[1], sys.argv[2]
hilos = int(sys.argv[3]) if len(sys.argv) > 3 else 6

frases = [l.rstrip("\n").split("\t") for l in open(DATOS / "frases.tsv")]

def normaliza(t):
    t = unicodedata.normalize("NFC", t.lower())
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()

if motor.startswith("cpp:"):
    import os, wave
    url = motor[4:].rstrip("/") + "/inference"
    # CTX=1: el codificador solo mira lo que dura el audio (50 tramas/s) y no 30 s enteros
    recorta = os.environ.get("CTX") == "1"
    def transcribe(wav):
        datos = {"language": "es", "response_format": "json", "temperature": "0"}
        if recorta:
            with wave.open(str(wav)) as w:
                datos["audio_ctx"] = str(min(1500, int(w.getnframes() / 16000 * 50) + 64))
        with open(wav, "rb") as a:
            r = requests.post(url, files={"file": a}, data=datos, timeout=180)
        r.raise_for_status()
        return r.json()["text"]
else:
    import wave, numpy as np
    from faster_whisper import WhisperModel
    modelo = WhisperModel(motor[3:], device="cpu", compute_type="int8", cpu_threads=hilos)
    def transcribe(wav):
        # El PCM ya en memoria: el PyAV que trae faster-whisper choca con esta versión
        with wave.open(str(wav)) as w:
            pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
        segs, _ = modelo.transcribe(pcm, language="es", beam_size=1,
                                    vad_filter=False, condition_on_previous_text=False)
        return " ".join(s.text for s in segs)

transcribe(DATOS / "tel3" / f"{frases[0][0]}.wav")  # calentar
t_corta, t_entera, rtf, refs, hips = [], [], [], [], []
with open(RES / f"{etiqueta}.tsv", "w") as out:
    for id_, hablante, dur, ref in frases:
        t0 = time.perf_counter(); transcribe(DATOS / "tel3" / f"{id_}.wav")
        t_corta.append(time.perf_counter() - t0)
        t0 = time.perf_counter(); hip = transcribe(DATOS / "tel" / f"{id_}.wav")
        dt = time.perf_counter() - t0
        t_entera.append(dt); rtf.append(dt / float(dur))
        refs.append(normaliza(ref)); hips.append(normaliza(hip))
        out.write(f"{id_}\t{dur}\t{t_corta[-1]:.3f}\t{dt:.3f}\t{hips[-1]}\n")

p95 = lambda xs: statistics.quantiles(xs, n=20)[18]
linea = (f"{etiqueta}\tWER {jiwer.wer(refs, hips)*100:.1f} %"
         f"\t3 s: mediana {statistics.median(t_corta)*1000:.0f} ms, p95 {p95(t_corta)*1000:.0f} ms"
         f"\tentera: RTF {statistics.median(rtf):.2f}, mediana {statistics.median(t_entera):.2f} s")
print(linea)
with open(RES / "resumen.tsv", "a") as r:
    r.write(linea + "\n")
