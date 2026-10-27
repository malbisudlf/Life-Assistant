"""Baja frases en español de Multilingual LibriSpeech (test) vía datasets-server de HF.
Una o dos por hablante, hasta N. Deja datos/mls/<id>.opus y datos/mls/frases.tsv."""
import json, sys, urllib.request, pathlib, collections
N = int(sys.argv[1]) if len(sys.argv) > 1 else 40
SALIDA = pathlib.Path.home() / "oido/datos/mls"
URL = ("https://datasets-server.huggingface.co/rows?dataset=facebook/multilingual_librispeech"
       "&config=spanish&split=test&offset={}&length=100")
por_hablante = collections.Counter()
elegidas = []
for offset in range(0, 2400, 100):
    with urllib.request.urlopen(URL.format(offset), timeout=60) as r:
        filas = json.load(r)["rows"]
    if not filas:
        break
    for f in filas:
        f = f["row"]
        if por_hablante[f["speaker_id"]] >= 2 or not (4 <= f["audio_duration"] <= 16):
            continue
        por_hablante[f["speaker_id"]] += 1
        elegidas.append(f)
    if len(elegidas) >= N:
        break
elegidas = elegidas[:N]
with open(SALIDA / "frases.tsv", "w") as tsv:
    for f in elegidas:
        destino = SALIDA / f"{f['id']}.opus"
        urllib.request.urlretrieve(f["audio"][0]["src"], destino)
        tsv.write(f"{f['id']}\t{f['speaker_id']}\t{f['audio_duration']:.2f}\t{f['transcript']}\n")
print(len(elegidas), "frases de", len(por_hablante), "hablantes,",
      round(sum(f["audio_duration"] for f in elegidas)), "s")
