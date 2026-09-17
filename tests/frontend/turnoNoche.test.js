import { describe, test, expect } from "vitest";
import { agruparParteNoche, fraseParteNoche, AREAS_NOCHE } from "../../src/lib/helpers";
import { nocheDeLlamadaDeUrl } from "../../src/lib/voz";

const parte = {
  fecha: "2026-09-14",
  items: [
    { id: "1", area: "correo", titulo: "¿Quedamos?", estado: "pendiente",
      datos: { de: "ana", categoria: "responder", borrador: true } },
    { id: "2", area: "correo", titulo: "Newsletter", estado: "aprobado",
      datos: { categoria: "ruido" } },
    { id: "3", area: "codigo", titulo: "Issue #7", estado: "pendiente", datos: {} },
  ],
};

describe("agruparParteNoche", () => {
  test("agrupa por area y cuenta lo que espera decision", () => {
    const r = agruparParteNoche(parte);
    expect(r.grupos.map(g => g.id)).toEqual(["correo", "codigo"]);
    expect(r.grupos[0].items).toHaveLength(2);
    expect(r.total).toBe(3);
    expect(r.pendientes).toBe(2);
    expect(r.borradores).toBe(1);
  });

  test("las areas vacias no se enseñan", () => {
    const r = agruparParteNoche({ items: [{ id: "1", area: "codigo", titulo: "x" }] });
    expect(r.grupos).toHaveLength(1);
    expect(AREAS_NOCHE.map(a => a.id)).toContain("agenda");
  });

  test("un parte que aun no ha llegado no cuenta como parte vacio", () => {
    // El widget dice «Cargando…» con null y «no hubo nada» con {}: decir «no hubo nada»
    // mientras carga seria mentir durante medio segundo.
    expect(agruparParteNoche(null).total).toBe(0);
    expect(agruparParteNoche(null).fecha).toBe("");
    expect(agruparParteNoche({ fecha: "2026-09-14", items: [] }).fecha).toBe("2026-09-14");
  });

  test("un parte con basura dentro no revienta", () => {
    expect(agruparParteNoche({ items: "no soy una lista" }).total).toBe(0);
    expect(agruparParteNoche({ items: [null, { area: "correo" }] }).total).toBe(2);
  });
});

describe("fraseParteNoche", () => {
  test("manda la frase del backend si viene", () => {
    // La escribe el backend porque la misma frase la DICE Jarvis al descolgar: dos
    // copias acaban siendo dos frases distintas.
    expect(fraseParteNoche({ ...parte, frase: "Esta noche: 12 correos." }))
      .toBe("Esta noche: 12 correos.");
  });

  test("sin frase del backend cuenta lo que hay", () => {
    const f = fraseParteNoche(parte);
    expect(f).toContain("3 cosas");
    expect(f).toContain("1 con la respuesta ya escrita");
  });

  test("un parte vacio lo dice, y uno que no existe no dice nada", () => {
    expect(fraseParteNoche({ items: [] })).toContain("nada");
    expect(fraseParteNoche(null)).toBe("");
  });

  test("una noche en blanco enseña lo que el backend dice que miro", () => {
    // El caso que motivó esto: sin la frase del backend, una noche sin correos se lee
    // igual que un turno averiado, y lo que se acaba creyendo es que no escribe nadie.
    expect(fraseParteNoche({
      fecha: "2026-09-17", items: [],
      frase: "Miré Bandeja de entrada y no había ningún correo sin leer de las últimas 24 h.",
    })).toContain("Bandeja de entrada");
  });
});

describe("nocheDeLlamadaDeUrl", () => {
  test("solo descuelga por la noche si se pide", () => {
    expect(nocheDeLlamadaDeUrl("?llamada=1&noche=1")).toBe(true);
    expect(nocheDeLlamadaDeUrl("?llamada=1")).toBe(false);
    expect(nocheDeLlamadaDeUrl("?noche=0")).toBe(false);
    expect(nocheDeLlamadaDeUrl("")).toBe(false);
  });
});
