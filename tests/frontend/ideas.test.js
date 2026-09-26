import { describe, test, expect } from "vitest";
import {
  IDEAS_VISIBLES, MIN_PALABRAS_COMUNES, UMBRAL_PARECIDAS, PALABRAS_VACIAS,
  normalizar, tokens, filtrarIdeas, coincideEnTitulo, etiquetaDe, etiquetasConCuenta,
  tramosCoincidencia, similitud, agruparParecidas, parecidaA,
  haceCuanto, fechaLarga, fechaCorta,
} from "../../src/lib/ideas";

// Dos redacciones de la misma idea, como las devolvería GPT-4o-mini en dos capturas.
const JAPON_1 = {
  id: "a", key: "Viaje a Japón en primavera", tag: "viajes", created_at: "2026-03-01T10:00:00Z",
  full_text: "Organizar un viaje a Japón en primavera para ver los cerezos en flor.",
};
const JAPON_2 = {
  id: "b", key: "Viajar a Japón para ver cerezos", tag: "Viajes", created_at: "2026-08-10T10:00:00Z",
  full_text: "Planear el viaje a Japón en primavera y ver los cerezos en flor en Kioto.",
};
const INFORME = {
  id: "x", key: "Informe trimestral", tag: "Trabajo", created_at: "2026-08-05T10:00:00Z",
  full_text: "Preparar el informe del trimestre para el jefe.",
};

describe("constantes", () => {
  test("los valores de partida", () => {
    expect(IDEAS_VISIBLES).toBe(10);
    expect(MIN_PALABRAS_COMUNES).toBe(2);
    expect(UMBRAL_PARECIDAS).toBe(0.35);
    expect(PALABRAS_VACIAS.has("usuario")).toBe(true);
  });
});

describe("normalizar", () => {
  test("quita tildes y mayúsculas y colapsa los espacios", () => {
    expect(normalizar("Trabajo")).toBe("trabajo");
    expect(normalizar("  trabajo ")).toBe("trabajo");
    expect(normalizar("trábajo")).toBe("trabajo");
    expect(normalizar("  Hola   MUNDO\n otra ")).toBe("hola mundo otra");
    expect(normalizar("Pingüino")).toBe("pinguino");
  });

  test("la ñ se conserva, también en mayúscula: «año» no es «ano»", () => {
    expect(normalizar("AÑO")).toBe("año");
    expect(normalizar("España".normalize("NFD"))).toBe("españa");
  });

  test("tolera null, undefined y números", () => {
    expect(normalizar(null)).toBe("");
    expect(normalizar(undefined)).toBe("");
    expect(normalizar(42)).toBe("42");
  });
});

describe("tokens", () => {
  test("quita palabras vacías y el relleno de GPT", () => {
    const t = tokens("La idea es que sería importante tener una forma de viajar");
    expect([...t]).toEqual(["viajar"]);
    expect(tokens("El usuario quiere hacer algo posible de otra manera").size).toBe(0);
  });

  test("descarta las palabras de menos de 3 letras", () => {
    expect([...tokens("ir al bar yo tu")]).toEqual(["bar"]);
  });

  test("plural ligero: solo a partir de 5 letras", () => {
    expect(tokens("viajes").has("viaje")).toBe(true);
    expect(tokens("casas").has("casa")).toBe(true);
    expect(tokens("mes").has("mes")).toBe(true);
    expect(tokens("gas").has("gas")).toBe(true);
    // «ideas» → «idea», que es vacía: no se cuela por el plural.
    expect(tokens("ideas").size).toBe(0);
  });

  test("la ñ se conserva y parte bien las palabras", () => {
    const t = tokens("Ruta por la montaña de España, año 2026");
    expect(t.has("montaña")).toBe(true);
    expect(t.has("españa")).toBe(true);
    expect(t.has("año")).toBe(true);
    expect(t.has("2026")).toBe(true);
  });

  test("devuelve un Set, vacío si no hay texto", () => {
    expect(tokens(null)).toBeInstanceOf(Set);
    expect(tokens(null).size).toBe(0);
  });
});

describe("filtrarIdeas", () => {
  const PRESUPUESTO = { id: "p", key: "Presupuesto", full_text: "El viajé del año pasado costó mucho", tag: "trabajo" };
  const SUELTA = { id: "s", key: "Nota suelta" };
  const IDEAS = [JAPON_1, PRESUPUESTO, INFORME, SUELTA];
  const ids = lista => lista.map(i => i.id);

  test("«viaje» encuentra el título con tilde y un full_text con «viajé»", () => {
    expect(ids(filtrarIdeas(IDEAS, { consulta: "viaje" }))).toEqual(["a", "p"]);
    expect(ids(filtrarIdeas(IDEAS, { consulta: "japon" }))).toEqual(["a"]);
  });

  test("varias palabras: tienen que estar todas", () => {
    expect(ids(filtrarIdeas(IDEAS, { consulta: "informe jefe" }))).toEqual(["x"]);
    expect(ids(filtrarIdeas(IDEAS, { consulta: "informe cerezos" }))).toEqual([]);
  });

  test("la etiqueta no distingue «Trabajo» de «trabajo»", () => {
    expect(ids(filtrarIdeas(IDEAS, { etiqueta: "trabajo" }))).toEqual(["p", "x"]);
    expect(ids(filtrarIdeas(IDEAS, { etiqueta: "Trabajo" }))).toEqual(["p", "x"]);
    expect(ids(filtrarIdeas(IDEAS, { etiqueta: "trabajo", consulta: "jefe" }))).toEqual(["x"]);
  });

  test("el chip «sin etiqueta» también filtra", () => {
    expect(ids(filtrarIdeas(IDEAS, { etiqueta: "sin etiqueta" }))).toEqual(["s"]);
  });

  test("una consulta de solo espacios no filtra, y el orden se mantiene", () => {
    expect(ids(filtrarIdeas(IDEAS, { consulta: "   " }))).toEqual(["a", "p", "x", "s"]);
    expect(ids(filtrarIdeas(IDEAS))).toEqual(["a", "p", "x", "s"]);
    const copia = filtrarIdeas(IDEAS);
    expect(copia).not.toBe(IDEAS);
  });

  test("tolera ideas null y una idea sin full_text, key ni tag", () => {
    expect(filtrarIdeas(null, { consulta: "x" })).toEqual([]);
    expect(filtrarIdeas(undefined)).toEqual([]);
    expect(ids(filtrarIdeas(IDEAS, { consulta: "suelta" }))).toEqual(["s"]);
    expect(filtrarIdeas([{ id: "v" }], { consulta: "algo" })).toEqual([]);
    expect(ids(filtrarIdeas([{ id: "v" }], { consulta: "" }))).toEqual(["v"]);
  });
});

describe("coincideEnTitulo", () => {
  test("dice si la búsqueda se explica con el título solo", () => {
    expect(coincideEnTitulo(JAPON_1, "japon")).toBe(true);
    expect(coincideEnTitulo(JAPON_1, "cerezos")).toBe(false);
    expect(coincideEnTitulo(JAPON_1, "japon cerezos")).toBe(false);
    expect(coincideEnTitulo(JAPON_1, "")).toBe(true);
    expect(coincideEnTitulo({}, "algo")).toBe(false);
  });
});

describe("etiquetas", () => {
  test("etiquetaDe normaliza y da «sin etiqueta» si no hay", () => {
    expect(etiquetaDe({ tag: " Trabajo " })).toBe("trabajo");
    expect(etiquetaDe({ tag: "" })).toBe("sin etiqueta");
    expect(etiquetaDe({ tag: null })).toBe("sin etiqueta");
    expect(etiquetaDe({})).toBe("sin etiqueta");
  });

  test("etiquetasConCuenta funde por normalización y ordena por cuenta y nombre", () => {
    const ideas = ["Trabajo", "trabajo", "salud", "", null, "ocio"].map((tag, i) => ({ id: i, tag }));
    expect(etiquetasConCuenta(ideas)).toEqual([
      { etiqueta: "sin etiqueta", cuenta: 2 },
      { etiqueta: "trabajo", cuenta: 2 },
      { etiqueta: "ocio", cuenta: 1 },
      { etiqueta: "salud", cuenta: 1 },
    ]);
    expect(etiquetasConCuenta(null)).toEqual([]);
  });
});

describe("tramosCoincidencia", () => {
  test("resalta «Japón» buscando «japon» y conserva la tilde", () => {
    expect(tramosCoincidencia("Viaje a Japón", "japon")).toEqual([
      { texto: "Viaje a ", marca: false },
      { texto: "Japón", marca: true },
    ]);
  });

  test("marca todas las apariciones de todas las palabras", () => {
    expect(tramosCoincidencia("Casa y más casa", "casa mas")).toEqual([
      { texto: "Casa", marca: true },
      { texto: " y ", marca: false },
      { texto: "más", marca: true },
      { texto: " ", marca: false },
      { texto: "casa", marca: true },
    ]);
  });

  test("los tramos solapados se funden en uno", () => {
    expect(tramosCoincidencia("Viajes", "viaje aje")).toEqual([
      { texto: "Viaje", marca: true },
      { texto: "s", marca: false },
    ]);
  });

  test("un texto en NFD resalta la letra con su tilde", () => {
    const nfd = "Japón".normalize("NFD");
    expect(tramosCoincidencia(nfd, "japon")).toEqual([{ texto: nfd, marca: true }]);
    expect(tramosCoincidencia("España".normalize("NFD"), "españa")[0].marca).toBe(true);
  });

  test("sin consulta o sin acierto, un solo tramo sin marca", () => {
    expect(tramosCoincidencia("Viaje a Japón", "")).toEqual([{ texto: "Viaje a Japón", marca: false }]);
    expect(tramosCoincidencia("Viaje a Japón", "   ")).toEqual([{ texto: "Viaje a Japón", marca: false }]);
    expect(tramosCoincidencia("Viaje a Japón", "china")).toEqual([{ texto: "Viaje a Japón", marca: false }]);
    expect(tramosCoincidencia(null, "x")).toEqual([{ texto: "", marca: false }]);
  });
});

describe("similitud y agruparParecidas", () => {
  // Construidas a mano para que los números salgan exactos: A~B y B~C con 3/7, A y C
  // sin nada en común.
  const A = { id: "A", key: "bicicleta montaña ruta casco", created_at: "2026-01-01T10:00:00Z" };
  const B = { id: "B", key: "bicicleta montaña ruta", full_text: "fotografia camara paisaje", created_at: "2026-02-01T10:00:00Z" };
  const C = { id: "C", key: "fotografia camara paisaje revelar", created_at: "2026-03-01T10:00:00Z" };

  test("dos redacciones casi iguales se parecen por encima del umbral", () => {
    expect(similitud(JAPON_1, JAPON_2)).toBeGreaterThanOrEqual(UMBRAL_PARECIDAS);
    expect(similitud(JAPON_1, INFORME)).toBe(0);
  });

  test("dos ideas que solo comparten palabras vacías no se parecen", () => {
    const gimnasio = { key: "Idea para el gimnasio", full_text: "La idea es que sería importante tener una forma de ir más al gimnasio." };
    const huerta = { key: "Idea sobre la huerta", full_text: "La idea es que sería importante tener una manera de regar la huerta." };
    expect(similitud(gimnasio, huerta)).toBe(0);
    expect(agruparParecidas([gimnasio, huerta])).toHaveLength(2);
  });

  test("una sola palabra en común no basta (MIN_PALABRAS_COMUNES)", () => {
    // Jaccard 1/2 = 0,5, por encima del umbral, pero comparten una palabra.
    expect(similitud({ key: "Gimnasio" }, { key: "Gimnasio mañana" })).toBe(0);
  });

  test("transitividad: A~B y B~C forman un grupo aunque A y C no se parezcan", () => {
    expect(similitud(A, B)).toBeCloseTo(3 / 7);
    expect(similitud(B, C)).toBeCloseTo(3 / 7);
    expect(similitud(A, C)).toBe(0);
    const grupos = agruparParecidas([C, B, A]);
    expect(grupos).toHaveLength(1);
    expect(grupos[0].miembros.map(m => m.id)).toEqual(["C", "B", "A"]);
  });

  test("la cabeza es la más reciente y `primera` la fecha de la más antigua", () => {
    const [grupo] = agruparParecidas([JAPON_1, JAPON_2]);
    expect(grupo.cabeza.id).toBe("b");
    expect(grupo.miembros.map(m => m.id)).toEqual(["b", "a"]);
    expect(grupo.primera).toBe(JAPON_1.created_at);
  });

  test("las ideas sin parecidas son grupos de uno, en el orden de la lista", () => {
    const grupos = agruparParecidas([INFORME, JAPON_2, JAPON_1]);
    expect(grupos.map(g => g.cabeza.id)).toEqual(["x", "b"]);
    expect(grupos[0].miembros).toHaveLength(1);
    expect(grupos[0].primera).toBe(INFORME.created_at);

    // El grupo va donde está su CABEZA (la más reciente), no su primer miembro.
    const alReves = agruparParecidas([JAPON_1, INFORME, JAPON_2]);
    expect(alReves.map(g => g.cabeza.id)).toEqual(["x", "b"]);
  });

  test("tolera listas vacías, null e ideas sin fecha", () => {
    expect(agruparParecidas(null)).toEqual([]);
    expect(agruparParecidas([])).toEqual([]);
    const [g] = agruparParecidas([{ id: "z", key: "algo suelto" }]);
    expect(g.primera).toBeNull();
  });

  test("agrupar no toca las ideas: mismos objetos, ninguno perdido", () => {
    const lista = [INFORME, JAPON_2, JAPON_1];
    const todos = agruparParecidas(lista).flatMap(g => g.miembros);
    expect(todos).toHaveLength(lista.length);
    for (const idea of lista) expect(todos).toContain(idea);
  });
});

describe("parecidaA", () => {
  test("encuentra la anterior y se excluye a sí misma por id", () => {
    expect(parecidaA(JAPON_2, [JAPON_2, INFORME, JAPON_1])).toBe(JAPON_1);
    expect(parecidaA(JAPON_2, [JAPON_2])).toBeNull();
  });

  test("null por debajo del umbral y con lista vacía", () => {
    expect(parecidaA(INFORME, [JAPON_1, JAPON_2])).toBeNull();
    expect(parecidaA(JAPON_2, [])).toBeNull();
    expect(parecidaA(JAPON_2, null)).toBeNull();
    expect(parecidaA(null, [JAPON_1])).toBeNull();
  });

  test("en empate gana la más antigua", () => {
    const vieja  = { ...JAPON_1, id: "v", created_at: "2025-05-01T10:00:00Z" };
    const menos  = { ...JAPON_1, id: "m", created_at: "2026-05-01T10:00:00Z" };
    expect(parecidaA(JAPON_2, [menos, vieja])).toBe(vieja);
    expect(parecidaA(JAPON_2, [vieja, menos])).toBe(vieja);
  });
});

describe("fechas", () => {
  const AHORA = new Date(2026, 5, 15, 12, 0);

  test("haceCuanto: hoy, ayer, días, 1 mes, meses y más de 12 meses", () => {
    expect(haceCuanto(new Date(2026, 5, 15, 0, 5), AHORA)).toBe("hoy");
    expect(haceCuanto(new Date(2026, 5, 14, 23, 50), AHORA)).toBe("ayer");
    expect(haceCuanto(new Date(2026, 5, 1), AHORA)).toBe("hace 14 días");
    expect(haceCuanto(new Date(2026, 4, 16), AHORA)).toBe("hace 1 mes");
    expect(haceCuanto(new Date(2026, 1, 10), AHORA)).toBe("hace 4 meses");
    expect(haceCuanto(new Date(2025, 6, 20), AHORA)).toBe("hace 11 meses");
    expect(haceCuanto(new Date(2025, 5, 1), AHORA)).toBe("hace 1 año");
    expect(haceCuanto(new Date(2023, 0, 1), AHORA)).toBe("hace 3 años");
  });

  test("haceCuanto: lo futuro es hoy y lo inválido no dice nada", () => {
    expect(haceCuanto(new Date(2026, 5, 20), AHORA)).toBe("hoy");
    expect(haceCuanto("no es fecha", AHORA)).toBe("");
    expect(haceCuanto(null, AHORA)).toBe("");
  });

  test("fechaLarga y fechaCorta: el año solo si no es el de ahora", () => {
    expect(fechaLarga(new Date(2026, 7, 3, 10), AHORA)).toBe("3 de agosto");
    expect(fechaLarga(new Date(2025, 7, 3, 10), AHORA)).toBe("3 de agosto de 2025");
    expect(fechaCorta(new Date(2026, 7, 3, 10), AHORA)).toBe("3 ago");
    expect(fechaCorta(new Date(2025, 11, 24, 10), AHORA)).toBe("24 dic 2025");
    expect(fechaLarga("", AHORA)).toBe("");
  });
});
