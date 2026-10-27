"""Referencia: whisper-1 de OpenAI (lo de hoy) sobre las mismas frases. Corre en el contenedor del backend."""
import time, re, statistics, unicodedata, pathlib
from openai import OpenAI
D = pathlib.Path("/tmp/w")
c = OpenAI()
def norm(t):
    t = unicodedata.normalize("NFC", t.lower()); t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()
def wer(refs, hips):
    e = n = 0
    for r, h in zip(refs, hips):
        r, h = r.split(), h.split(); n += len(r)
        d = list(range(len(h) + 1))
        for i in range(1, len(r) + 1):
            p, d[0] = d[0], i
            for j in range(1, len(h) + 1):
                p, d[j] = d[j], min(d[j] + 1, d[j-1] + 1, p + (r[i-1] != h[j-1]))
        e += d[-1]
    return e / n
tc, te, refs, hips = [], [], [], []
for l in open(D / "frases.tsv"):
    id_, _, dur, ref = l.rstrip("\n").split("\t")
    t0 = time.perf_counter(); c.audio.transcriptions.create(model="whisper-1", file=open(D/"tel3"/f"{id_}.wav","rb"), language="es"); tc.append(time.perf_counter()-t0)
    t0 = time.perf_counter(); h = c.audio.transcriptions.create(model="whisper-1", file=open(D/"tel"/f"{id_}.wav","rb"), language="es").text; te.append(time.perf_counter()-t0)
    refs.append(norm(ref)); hips.append(norm(h))
q = statistics.quantiles(tc, n=20)[18]
print(f"openai-whisper-1\tWER {wer(refs,hips)*100:.1f} %\t3 s: mediana {statistics.median(tc)*1000:.0f} ms, p95 {q*1000:.0f} ms\tentera: mediana {statistics.median(te):.2f} s")
