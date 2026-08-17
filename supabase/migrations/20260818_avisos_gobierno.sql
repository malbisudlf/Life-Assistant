-- Gobierno de los avisos: prioridad, caducidad, huella y utilidad.
--
-- Un asistente proactivo tiene exactamente un modo de fallo: volverse ruido. Y no falla
-- de golpe — falla porque cada regla nueva parece razonable por separado, hasta que un
-- día se dejan de leer todos los avisos a la vez. Hasta aquí cada regla escribía su
-- aviso, ninguna competía con las demás y ninguna sabía si había servido de algo.
--
-- Las columnas nuevas de `jarvis_recordatorios` son lo que permite que compitan:
--   * `regla`     — quién lo manda. NULL = lo pediste tú, y eso NUNCA se gobierna:
--                   ni tope, ni silenciado. Obedecer al presupuesto antes que a quien
--                   pidió el recordatorio sería el sitio equivocado.
--   * `prioridad` — 1 lo que caduca en minutos, 8 lo que da igual leer mañana.
--   * `caduca`    — un "sal ya" entregado tarde no vale; se descarta en vez de mentir.
--   * `huella`    — la situación que lo motivó. Impide repetir el mismo aviso siete días
--                   seguidos: la idempotencia vieja era por DÍA, así que "llevas 3 días
--                   sin entrenar" salía el jueves, el viernes y el sábado.
--   * `voz`       — además del móvil, que se oiga (Alexa) si estás en casa.
--   * `util`      — la respuesta del botón del aviso. NULL = no contestaste, que NO es
--                   lo mismo que "no me sirvió" y no cuenta como negativa.
alter table public.jarvis_recordatorios
  add column if not exists regla      text,
  add column if not exists prioridad  integer     not null default 5,
  add column if not exists caduca     timestamptz,
  add column if not exists huella     text,
  add column if not exists voz        boolean     not null default false,
  add column if not exists util       boolean,
  add column if not exists enviado_at timestamptz;

-- El despacho ordena por prioridad y el presupuesto cuenta lo ya enviado hoy.
create index if not exists jarvis_recordatorios_despacho
  on public.jarvis_recordatorios (enviado, cuando, prioridad);
-- Y la memoria de lo ya dicho pregunta por (regla, huella) reciente.
create index if not exists jarvis_recordatorios_huella
  on public.jarvis_recordatorios (regla, huella, creado);

-- Estadística por regla, que es lo que hace que el sistema mejore solo: una regla cuyos
-- avisos se marcan como inútiles se silencia sola.
--
-- El silenciado tiene que ser VISIBLE: una regla apagada en silencio es exactamente el
-- error que persigue el resto del proyecto. Por eso se avisa al silenciarla y sale en
-- `GET /avisos/estado`.
create table if not exists public.avisos_reglas (
  regla            text        primary key,
  enviados         integer     not null default 0,
  utiles           integer     not null default 0,
  no_utiles        integer     not null default 0,
  silenciada       boolean     not null default false,
  silenciada_desde timestamptz,
  ultima_vez       timestamptz
);

alter table public.avisos_reglas enable row level security;
