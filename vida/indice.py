"""El índice de la vida: lo que se busca con «¿qué le regalé a mi madre el año pasado?».

Lógica pura sobre SQLite (FTS5, de la biblioteca estándar): guardar documentos, buscarlos
y decir cuántos hay. Sin red y sin modelo: lo usa `servidor.py` en jacobo y lo prueban
los tests del repositorio (tests/backend/test_vida_indice.py). Ver docs/VIDA.md.

Un documento es una cosa con fecha: un WhatsApp, un correo, un evento del calendario, una
idea. Tiene un `id` estable que pone quien lo manda (el backend), así que mandarlo dos
veces lo deja igual: se reescribe, no se duplica.

La búsqueda es por palabras, no por significado, y es a propósito: la pregunta la
convierte en palabras Jarvis (el modelo que ya está pagado en cada turno), que sabe que
«regalo de mi madre» también puede ser «cumpleaños ama» o «perfume». Un modelo de
vectores aquí sería otro servicio que mantener para ganar poco: lo que Mikel busca son
cosas que dijo con palabras concretas.
"""

import json
import re
import sqlite3
import threading
import unicodedata

FUENTE_RE   = re.compile(r"^[a-z_]{1,20}$")
ID_MAX      = 200
TITULO_MAX  = 200
TEXTO_MAX   = 4000
QUIEN_MAX   = 80
LIMITE_MAX  = 40
# Palabras que no ayudan a encontrar nada y que, en modo «todas», dejarían sin resultados
# una búsqueda que Jarvis escriba en lenguaje natural.
VACIAS = frozenset("""
a al algo ante con contra de del desde donde durante el ella ellas ellos en entre era es
esa ese eso esta este esto fue fui ha han hasta la las le les lo los me mi mis muy nos o
para pero por que quien se sea si sin sobre su sus te tu tus un una uno unos unas y ya yo
cuando cual como mas otra otro hace hizo vez veces ultima ultimo pasado pasada año ano
""".split())

_ESQUEMA = """
create table if not exists docs (
    id      text primary key,
    fuente  text not null,
    fecha   text not null,
    titulo  text not null default '',
    texto   text not null default '',
    quien   text not null default '',
    extra   text not null default '{}'
);
create index if not exists docs_fuente_fecha on docs (fuente, fecha);
create virtual table if not exists docs_fts using fts5(
    titulo, texto, quien,
    content='docs', content_rowid='rowid',
    tokenize="unicode61 remove_diacritics 2"
);
create trigger if not exists docs_ai after insert on docs begin
    insert into docs_fts(rowid, titulo, texto, quien)
    values (new.rowid, new.titulo, new.texto, new.quien);
end;
create trigger if not exists docs_ad after delete on docs begin
    insert into docs_fts(docs_fts, rowid, titulo, texto, quien)
    values ('delete', old.rowid, old.titulo, old.texto, old.quien);
end;
create trigger if not exists docs_au after update on docs begin
    insert into docs_fts(docs_fts, rowid, titulo, texto, quien)
    values ('delete', old.rowid, old.titulo, old.texto, old.quien);
    insert into docs_fts(rowid, titulo, texto, quien)
    values (new.rowid, new.titulo, new.texto, new.quien);
end;
"""


class DocumentoMalo(ValueError):
    """Un documento que no se guarda. El texto dice por qué (sin repetir su contenido)."""


def plano(texto) -> str:
    """Sin tildes, en minúsculas y con los signos como espacios: lo que se compara."""
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^\w]+", " ", t).split())


def raiz(palabra: str) -> str:
    """Un plural o un tiempo verbal no pueden esconder lo buscado: «regalos», «regalé» y
    «regalo» acaban en «regal», que con el prefijo de FTS5 detrás los encuentra a todos.
    Corto a propósito: quitar el plural y, en las largas, la última vocal."""
    if len(palabra) > 5 and palabra.endswith("ones"):
        palabra = palabra[:-2]
    elif len(palabra) > 4 and palabra.endswith("es") and palabra[-3] not in "aeiou":
        palabra = palabra[:-2]
    elif len(palabra) > 3 and palabra.endswith("s"):
        palabra = palabra[:-1]
    if len(palabra) >= 6 and palabra[-1] in "aeiou":
        palabra = palabra[:-1]
    return palabra


def palabras(consulta: str) -> list:
    """Las palabras que de verdad se buscan, sin repetir y en orden."""
    vistas, salida = set(), []
    for p in plano(consulta).split():
        if p in VACIAS or (len(p) < 2 and not p.isdigit()):
            continue
        r = raiz(p)
        if r not in vistas:
            vistas.add(r)
            salida.append(r)
    return salida[:12]


def consulta_fts(lista: list, todas: bool = True) -> str:
    """De palabras a la consulta de FTS5. Cada una entre comillas (así ningún carácter
    cuenta como operador) y, si tiene cuatro letras o más, como prefijo."""
    trozos = [f'"{p}"*' if len(p) >= 4 else f'"{p}"' for p in lista]
    return (" " if todas else " OR ").join(trozos)


def _limpio(doc) -> tuple:
    if not isinstance(doc, dict):
        raise DocumentoMalo("no es un objeto")
    id_ = str(doc.get("id") or "").strip()
    fuente = str(doc.get("fuente") or "").strip()
    fecha = str(doc.get("fecha") or "").strip()
    if not id_ or len(id_) > ID_MAX:
        raise DocumentoMalo("id vacío o largo")
    if not FUENTE_RE.match(fuente):
        raise DocumentoMalo("fuente no válida")
    if not re.match(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?)?", fecha):
        raise DocumentoMalo("fecha no válida")
    texto = str(doc.get("texto") or "")[:TEXTO_MAX]
    titulo = str(doc.get("titulo") or "")[:TITULO_MAX]
    if not (texto.strip() or titulo.strip()):
        raise DocumentoMalo("sin texto")
    extra = doc.get("extra") if isinstance(doc.get("extra"), dict) else {}
    return (id_, fuente, fecha[:25], titulo, texto, str(doc.get("quien") or "")[:QUIEN_MAX],
            json.dumps(extra, ensure_ascii=False)[:1000])


class Indice:
    """Una base SQLite con su lock: el servidor la usa desde varios hilos."""

    def __init__(self, ruta: str = ":memory:"):
        self._db = sqlite3.connect(ruta, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute("pragma journal_mode=wal")
            self._db.executescript(_ESQUEMA)
            self._db.commit()

    def guardar(self, docs: list) -> dict:
        """Guarda (o reescribe por `id`) los que valen. {guardados, rechazados}."""
        filas, rechazados = [], 0
        for d in docs or []:
            try:
                filas.append(_limpio(d))
            except DocumentoMalo:
                rechazados += 1
        with self._lock:
            self._db.executemany(
                "insert into docs (id, fuente, fecha, titulo, texto, quien, extra) "
                "values (?, ?, ?, ?, ?, ?, ?) on conflict(id) do update set "
                "fuente=excluded.fuente, fecha=excluded.fecha, titulo=excluded.titulo, "
                "texto=excluded.texto, quien=excluded.quien, extra=excluded.extra", filas)
            self._db.commit()
        return {"guardados": len(filas), "rechazados": rechazados}

    def buscar(self, consulta: str, fuentes=None, desde: str = "", hasta: str = "",
               limite: int = 10) -> dict:
        """Lo que más se parece, primero. Primero con TODAS las palabras; si no sale nada,
        con cualquiera (y lo dice, `modo`), porque una palabra de más no puede dejar a
        Jarvis creyendo que no existe."""
        lista = palabras(consulta)
        if not lista:
            return {"modo": "", "palabras": [], "resultados": []}
        try:
            limite = max(1, min(int(limite or 10), LIMITE_MAX))
        except (TypeError, ValueError):
            limite = 10
        filtros, params = [], []
        fuentes = [f for f in (fuentes or []) if FUENTE_RE.match(str(f))]
        if fuentes:
            filtros.append("d.fuente in (%s)" % ",".join("?" * len(fuentes)))
            params += fuentes
        if re.match(r"^\d{4}-\d{2}-\d{2}", desde or ""):
            filtros.append("d.fecha >= ?")
            params.append(desde[:10])
        if re.match(r"^\d{4}-\d{2}-\d{2}", hasta or ""):
            filtros.append("d.fecha < ?")
            params.append(hasta[:10] + "~")       # «~» va después de cualquier hora
        donde = (" and " + " and ".join(filtros)) if filtros else ""
        sql = ("select d.id, d.fuente, d.fecha, d.titulo, d.quien, d.extra, "
               "snippet(docs_fts, 1, '«', '»', '…', 28) as fragmento, "
               "bm25(docs_fts, 2.0, 1.0, 1.5) as rango "
               "from docs_fts join docs d on d.rowid = docs_fts.rowid "
               f"where docs_fts match ?{donde} order by rango limit ?")
        for modo, todas in (("todas", True), ("alguna", False)):
            if modo == "alguna" and len(lista) < 2:
                break
            with self._lock:
                filas = self._db.execute(sql, [consulta_fts(lista, todas), *params, limite]).fetchall()
            if filas:
                return {"modo": modo, "palabras": lista, "resultados": [self._fila(f) for f in filas]}
        return {"modo": "", "palabras": lista, "resultados": []}

    @staticmethod
    def _fila(f) -> dict:
        d = {"id": f["id"], "fuente": f["fuente"], "fecha": f["fecha"],
             "fragmento": f["fragmento"] or ""}
        if f["titulo"]:
            d["titulo"] = f["titulo"]
        if f["quien"]:
            d["quien"] = f["quien"]
        try:
            extra = json.loads(f["extra"] or "{}")
        except ValueError:
            extra = {}
        if extra:
            d["extra"] = extra
        return d

    def estado(self) -> dict:
        """Cuántos hay de cada fuente y el más reciente: de aquí sale por dónde sigue el
        backend al alimentarlo (no hay que guardar ningún cursor en otro sitio)."""
        with self._lock:
            filas = self._db.execute("select fuente, count(*) as n, max(fecha) as ultimo "
                                     "from docs group by fuente").fetchall()
        return {f["fuente"]: {"n": f["n"], "ultimo": f["ultimo"]} for f in filas}

    def olvidar(self, fuente: str = "", ids=None) -> int:
        """Borra una fuente entera o unos ids. Devuelve cuántos."""
        with self._lock:
            if ids:
                ids = [str(i)[:ID_MAX] for i in ids][:1000]
                cur = self._db.execute("delete from docs where id in (%s)" % ",".join("?" * len(ids)), ids)
            elif FUENTE_RE.match(fuente or ""):
                cur = self._db.execute("delete from docs where fuente = ?", (fuente,))
            else:
                return 0
            self._db.commit()
            return cur.rowcount
