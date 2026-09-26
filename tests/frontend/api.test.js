// Único sitio que toca el esquema de autenticación del cliente (ver CLAUDE.md,
// tabla de ficheros clave) y hasta ahora sin tests propios: lo que rompa aquí
// afecta a TODAS las llamadas autenticadas del dashboard y de la zona dev.
import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { authHeaders, jsonHeaders, apiFetch } from "../../src/lib/api";

// jsdom no deja redefinir `location.reload` con vi.spyOn (es no configurable de
// serie): hay que sustituir el objeto `location` entero, como en el flujo de login
// (ver docs/TESTS.md, "El input de contraseña...").
function mockReload() {
  const original = window.location;
  const reload = vi.fn();
  Object.defineProperty(window, "location", {
    value: { ...original, reload },
    writable: true,
    configurable: true,
  });
  return reload;
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("authHeaders / jsonHeaders", () => {
  test("sin token en localStorage, manda el Bearer vacío", () => {
    expect(authHeaders()).toEqual({ Authorization: "Bearer " });
  });

  test("lee el token en el momento de llamar, no en un closure capturado antes", () => {
    // El comentario del fichero lo dice explícitamente: si la sesión se renueva a
    // mitad de una pantalla, la siguiente llamada tiene que ver el token nuevo.
    localStorage.setItem("la_token", "token-viejo");
    const primero = authHeaders();
    localStorage.setItem("la_token", "token-nuevo");
    const segundo = authHeaders();

    expect(primero).toEqual({ Authorization: "Bearer token-viejo" });
    expect(segundo).toEqual({ Authorization: "Bearer token-nuevo" });
  });

  test("las cabeceras extra se añaden sin pisar el Authorization", () => {
    localStorage.setItem("la_token", "abc");
    expect(authHeaders({ "X-Otra": "1" })).toEqual({
      Authorization: "Bearer abc",
      "X-Otra": "1",
    });
  });

  test("jsonHeaders añade Content-Type además del Bearer", () => {
    localStorage.setItem("la_token", "abc");
    expect(jsonHeaders()).toEqual({
      Authorization: "Bearer abc",
      "Content-Type": "application/json",
    });
  });
});

describe("apiFetch", () => {
  test("una respuesta normal se devuelve tal cual, sin tocar la sesión", async () => {
    localStorage.setItem("la_token", "abc");
    const reload = mockReload();
    const res = { status: 200, ok: true, json: async () => ({}) };
    globalThis.fetch = vi.fn().mockResolvedValue(res);

    const r = await apiFetch("https://backend/x", { headers: authHeaders() });

    expect(r).toBe(res);
    expect(localStorage.getItem("la_token")).toBe("abc");
    expect(reload).not.toHaveBeenCalled();
  });

  test("un 401 con sesión activa borra el token y recarga", async () => {
    // El caso documentado en docs/BUGS_HISTORICOS.md: caducar la sesión de verdad
    // tiene que echar al usuario a login. apiFetch espera 1s de verdad tras recargar
    // (para dar tiempo a que la navegación se lleve por delante el resto del código);
    // se fijan los timers para no alargar la suite ese segundo.
    localStorage.setItem("la_token", "abc");
    const reload = mockReload();
    globalThis.fetch = vi.fn().mockResolvedValue({ status: 401, ok: false, json: async () => ({}) });

    vi.useFakeTimers();
    const promesa = apiFetch("https://backend/x");
    await vi.runAllTimersAsync();
    await promesa;
    vi.useRealTimers();

    expect(localStorage.getItem("la_token")).toBeNull();
    expect(reload).toHaveBeenCalledTimes(1);
  });

  test("un 401 sin sesión no recarga nada", async () => {
    // Sin esta guarda, los useEffect de carga inicial que llaman a la API antes de
    // que haya token disparaban un bucle infinito de recargas en el login (ver
    // docs/BUGS_HISTORICOS.md, "Bucle infinito de recargas en el login móvil").
    // Se espía también el borrado: mirar solo que el token siga en null no distingue
    // nada (sin sesión ya lo estaba), y lo que delata la versión rota es que llega a
    // entrar en la rama de cerrar sesión.
    const reload = mockReload();
    const borrar = vi.spyOn(Storage.prototype, "removeItem");
    globalThis.fetch = vi.fn().mockResolvedValue({ status: 401, ok: false, json: async () => ({}) });

    const res = await apiFetch("https://backend/x");

    expect(res.status).toBe(401);
    expect(reload).not.toHaveBeenCalled();
    expect(borrar).not.toHaveBeenCalled();
  });

  test("el token se lee en el momento de la llamada, no en un closure", async () => {
    // Si la sesión se renueva a mitad de una pantalla, la siguiente llamada tiene que
    // usar el token nuevo sin que nadie reconstruya nada.
    globalThis.fetch = vi.fn().mockResolvedValue({ status: 200, ok: true, json: async () => ({}) });
    localStorage.setItem("la_token", "viejo");
    await apiFetch("https://backend/x", { headers: authHeaders() });
    localStorage.setItem("la_token", "nuevo");
    await apiFetch("https://backend/x", { headers: authHeaders() });

    const [[, opts1], [, opts2]] = globalThis.fetch.mock.calls;
    expect(opts1.headers.Authorization).toBe("Bearer viejo");
    expect(opts2.headers.Authorization).toBe("Bearer nuevo");
  });

  test("otros errores (404, 500) no tocan la sesión", async () => {
    localStorage.setItem("la_token", "abc");
    const reload = mockReload();
    globalThis.fetch = vi.fn().mockResolvedValue({ status: 500, ok: false, json: async () => ({}) });

    await apiFetch("https://backend/x");

    expect(localStorage.getItem("la_token")).toBe("abc");
    expect(reload).not.toHaveBeenCalled();
  });
});
