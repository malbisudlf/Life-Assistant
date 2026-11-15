"""El espejo de parches (`docs/JARVIS_PARCHES_ESPEJO.md`): la puerta, el informe y el rastro.

Lo que se protege: un parche de Jarvis no toca el núcleo de seguridad, no amplía lo que
Jarvis puede hacer sin que Mikel lo haya aprobado por su nombre, no quita confirmaciones,
nace apagado y trae su prueba; el informe solo pregunta «¿Lo despliego?» si todo pasó en
un espejo aislado; y el rastro no admite un parche propuesto por un mensaje ni una
aprobación que no sea de Mikel con sus palabras.
"""
import importlib.util
import json
import os

import pytest

RAIZ = os.path.join(os.path.dirname(__file__), "..", "..")


def _cargar(nombre):
    spec = importlib.util.spec_from_file_location(nombre, os.path.join(RAIZ, "espejo", f"{nombre}.py"))
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


espejo = _cargar("espejo")
comparar = _cargar("comparar")
NUCLEO = espejo.cargar_nucleo()

PRUEBA = ("tests/backend/test_citas.py", ["def test_recuerda_la_cita():", "    assert True"], [])


def _diff(*ficheros):
    """Un `git diff` de mentira: (ruta, [líneas añadidas], [líneas quitadas])."""
    trozos = []
    for ruta, mas, menos in ficheros:
        trozos += [f"diff --git a/{ruta} b/{ruta}", f"--- a/{ruta}", f"+++ b/{ruta}", "@@ -1,3 +1,3 @@"]
        trozos += [f"-{l}" for l in menos] + [f"+{l}" for l in mas]
    return "\n".join(trozos) + "\n"


BUENO = _diff(("backend/main.py", ['PARCHE_50 = _flag("PARCHE_50", "0")',
                                   "def _citas_del_medico():", "    return []"], []), PRUEBA)
PASA = {"aislado": True, "unitarias": {"pasan": 4300, "fallan": 0, "nuevas": 1},
        "conversacion": {"pasan": 900, "regresiones": 0}}


class TestLaPuerta:
    def test_un_parche_limpio_pasa(self):
        v = espejo.revisar(BUENO, NUCLEO)
        assert v["ok"] and v["rechazos"] == [] and v["con_interruptor"]

    @pytest.mark.parametrize("ruta", [
        "backend/nucleo_seguridad.json", "backend/anticipa.py", "espejo/espejo.py",
        "espejo/canario.sh", ".github/workflows/ci.yml", "backend/requirements.txt",
        "telefono/RUNBOOK.md", "tests/backend/test_ajeno.py", "tests/backend/test_espejo.py",
        "supabase/migrations/20261201_algo.sql", "CLAUDE.md"])
    def test_las_rutas_protegidas_se_rechazan(self, ruta):
        v = espejo.revisar(_diff((ruta, ["x = 1"], [])), NUCLEO)
        assert not v["ok"] and any("ruta protegida" in r for r in v["rechazos"])

    def test_renombrar_un_fichero_protegido_es_tocarlo(self):
        texto = ("diff --git a/backend/nucleo_seguridad.json b/backend/viejo.json\n"
                 "similarity index 100%\nrename from backend/nucleo_seguridad.json\nrename to backend/viejo.json\n")
        assert not espejo.revisar(texto, NUCLEO)["ok"]

    @pytest.mark.parametrize("linea", [
        "def _ajeno_bloquea(nombre, fuentes):",
        '_HERRAMIENTAS_AJENAS = frozenset({"whatsapp_leer"})',
        'PREGUNTAS_ACCIONES.add("desplegar")',
        "_TRAS_AJENO_SE_PUEDE |= {'desplegar'}",
        'setattr(main, "_jarvis_confirma", lambda *a: False)',
        "def verify_token(credentials=None):",
        "ANTICIPA_SUGIERE = True",
        "def _anticipa_apuntar(*a): pass",
        "_CASA_DIRECTOS = _CASA_DOMINIOS",
    ])
    def test_redefinir_o_escribir_en_el_nucleo_se_rechaza(self, linea):
        v = espejo.revisar(_diff(("backend/main.py", [linea], []), PRUEBA), NUCLEO)
        assert not v["ok"] and any("núcleo" in r for r in v["rechazos"]), v

    def test_quitar_una_linea_que_nombra_el_nucleo_se_rechaza(self):
        v = espejo.revisar(_diff(("backend/main.py", ["    pass"],
                                  ["    bloqueo = _ajeno_bloquea(nombre, ajeno)"]), PRUEBA), NUCLEO)
        assert not v["ok"]

    def test_usar_el_nucleo_si_se_puede(self):
        mas = ['PARCHE_51 = _flag("PARCHE_51", "0")',
               "def citas(credentials=Depends(verify_token)):",
               "    if _token_ok(token, HA_POLL_TOKEN) and not _en_clase():",
               "        return _jarvis_confirma(herramienta, argumentos)"]
        assert espejo.revisar(_diff(("backend/main.py", mas, []), PRUEBA), NUCLEO)["ok"]

    def test_una_herramienta_nueva_necesita_su_nombre_aprobado(self):
        mas = ['PARCHE_52 = _flag("PARCHE_52", "0")', '    "citas_medico": {',
               '        "confirmar":   False,', '        "fn":          _j_citas,']
        texto = _diff(("backend/main.py", mas, []), PRUEBA)
        v = espejo.revisar(texto, NUCLEO)
        assert not v["ok"] and v["capacidades_nuevas"] == ["citas_medico"]
        assert espejo.revisar(texto, NUCLEO, ("otra",))["ok"] is False
        assert espejo.revisar(texto, NUCLEO, ("citas_medico",))["ok"] is True

    def test_quitar_una_confirmacion_se_rechaza(self):
        v = espejo.revisar(_diff(("backend/main.py", ['        "confirmar":   False,'],
                                  ['        "confirmar":   True,']), PRUEBA), NUCLEO)
        assert not v["ok"] and any("confirmación" in r for r in v["rechazos"])

    def test_un_interruptor_que_nace_encendido_se_rechaza(self):
        for linea in ('PARCHE_53 = _flag("PARCHE_53")', 'PARCHE_53 = _flag("PARCHE_53", "1")'):
            v = espejo.revisar(_diff(("backend/main.py", [linea], []), PRUEBA), NUCLEO)
            assert not v["ok"] and any("nace encendido" in r for r in v["rechazos"])

    def test_sin_prueba_nueva_no_se_presenta(self):
        v = espejo.revisar(_diff(("backend/main.py", ['PARCHE_54 = _flag("PARCHE_54", "0")'], [])), NUCLEO)
        assert not v["ok"] and any("prueba" in r for r in v["rechazos"])

    def test_sin_interruptor_avisa_pero_no_rechaza(self):
        v = espejo.revisar(_diff(("backend/main.py", ["def _f():", "    return 1"], []), PRUEBA), NUCLEO)
        assert v["ok"] and any("PARCHE_NN" in a for a in v["avisos"])
        assert espejo.riesgo(v) == "medio"

    def test_un_diff_vacio_no_pasa(self):
        assert not espejo.revisar("", NUCLEO)["ok"]

    def test_la_documentacion_sola_no_necesita_prueba(self):
        assert espejo.revisar(_diff(("docs/JARVIS.md", ["una línea"], [])), NUCLEO)["ok"]

    def test_las_rutas_protegidas_existen(self):
        # Una lista de rutas que ya no existen protege a nadie.
        for ruta in NUCLEO["parches"]["rutas_protegidas"]:
            assert os.path.exists(os.path.join(RAIZ, ruta)), ruta

    def test_el_espejo_y_el_nucleo_se_protegen_a_si_mismos(self):
        rutas = NUCLEO["parches"]["rutas_protegidas"]
        assert "espejo/" in rutas and "backend/nucleo_seguridad.json" in rutas
        assert "tests/backend/test_espejo.py" in rutas


class TestElInforme:
    def test_tres_lineas_y_una_pregunta(self):
        texto = espejo.informe(espejo.revisar(BUENO, NUCLEO), PASA, "recuerda las citas del médico")
        lineas = texto.split("\n")
        assert len(lineas) == 4 and lineas[3] == "¿Lo despliego?"
        assert lineas[0].startswith("Qué cambia: recuerda las citas del médico (2 ficheros")
        assert "4300 pruebas en el espejo sin red" in lineas[1]
        assert lineas[2] == "Riesgo: bajo."

    def test_rechazado_no_pregunta(self):
        v = espejo.revisar(_diff(("backend/nucleo_seguridad.json", ["x"], [])), NUCLEO)
        texto = espejo.informe(v, {}, "amplía permisos")
        assert "¿Lo despliego?" not in texto and "Riesgo: alto" in texto and "ruta protegida" in texto

    @pytest.mark.parametrize("pruebas", [
        {**PASA, "aislado": False},
        {**PASA, "unitarias": {"pasan": 4299, "fallan": 1, "nuevas": 1}},
        {**PASA, "conversacion": {"pasan": 899, "regresiones": 1}},
        {**PASA, "unitarias": {"pasan": 0, "fallan": 0, "nuevas": 0}},
        {},
    ])
    def test_si_algo_no_paso_no_pregunta(self, pruebas):
        texto = espejo.informe(espejo.revisar(BUENO, NUCLEO), pruebas, "x")
        assert "¿Lo despliego?" not in texto and "No se despliega" in texto


class TestElRastro:
    def test_solo_se_anade(self, tmp_path):
        rastro = str(tmp_path / "r.jsonl")
        espejo.apuntar(rastro, "p1", "propuesto", {"propuesto_por": "mikel", "rama": "arreglo/x"})
        espejo.apuntar(rastro, "p1", "probado", {"pasa": "si"})
        espejo.apuntar(rastro, "p1", "aprobado", {"aprobado_por": "mikel", "literal": "sí, despliégalo"})
        pasos = [json.loads(l) for l in open(rastro, encoding="utf-8")]
        assert [p["paso"] for p in pasos] == ["propuesto", "probado", "aprobado"]
        assert all(p["parche"] == "p1" and p["ts"] for p in pasos)

    @pytest.mark.parametrize("quien", ["whatsapp", "correo", "jarvis:mensaje", "", "aimar"])
    def test_un_mensaje_ajeno_no_propone_un_parche(self, tmp_path, quien):
        with pytest.raises(ValueError):
            espejo.apuntar(str(tmp_path / "r.jsonl"), "p1", "propuesto", {"propuesto_por": quien})

    def test_la_aprobacion_es_de_mikel_con_sus_palabras(self, tmp_path):
        rastro = str(tmp_path / "r.jsonl")
        for datos in ({"aprobado_por": "jarvis", "literal": "sí"}, {"aprobado_por": "mikel"},
                      {"aprobado_por": "mikel", "literal": ""}):
            with pytest.raises(ValueError):
                espejo.apuntar(rastro, "p1", "aprobado", datos)
        assert not os.path.exists(rastro)


class TestComparar:
    def test_lo_que_pasaba_y_ya_no_pasa_es_una_regresion(self):
        base = {"tests.backend.test_jarvis.T::a": "pasa", "tests.backend.test_main.T::b": "pasa",
                "tests.backend.test_main.T::c": "falla"}
        rama = {"tests.backend.test_jarvis.T::a": "falla", "tests.backend.test_main.T::b": "pasa",
                "tests.backend.test_main.T::c": "falla", "tests.backend.test_citas::nueva": "pasa"}
        r = comparar.comparar(base, rama)
        assert r["regresiones"] == ["tests.backend.test_jarvis.T::a"]
        assert r["conversacion"]["regresiones"] == 1 and r["unitarias"]["nuevas"] == 1

    def test_una_prueba_borrada_cuenta_como_regresion(self):
        r = comparar.comparar({"m.t::a": "pasa", "m.t::b": "pasa"}, {"m.t::a": "pasa"})
        assert r["regresiones"] == ["m.t::b"]

    def test_sin_main_no_hay_con_que_comparar(self, tmp_path, capsys):
        rama = tmp_path / "rama.xml"
        rama.write_text('<testsuite><testcase classname="m.t" name="a"/></testsuite>', encoding="utf-8")
        comparar.main(["comparar.py", str(tmp_path / "no-existe.xml"), str(rama)])
        r = json.loads(capsys.readouterr().out)
        assert r["comparable"] is False and r["unitarias"]["fallan"] >= 1

    def test_lee_el_xml_de_pytest(self, tmp_path):
        xml = tmp_path / "x.xml"
        xml.write_text('<testsuites><testsuite>'
                       '<testcase classname="m.t" name="a"/>'
                       '<testcase classname="m.t" name="b"><failure/></testcase>'
                       '<testcase classname="m.t" name="c"><skipped/></testcase>'
                       '</testsuite></testsuites>', encoding="utf-8")
        assert comparar.leer(str(xml)) == {"m.t::a": "pasa", "m.t::b": "falla", "m.t::c": "saltada"}
