-- Un latido por proceso del backend, para saber si hay DOS vivos contra este Supabase.
--
-- Es la avería silenciosa que más veces ha vuelto en este proyecto: Fly despierto por un
-- Atajo sin repuntar que reservaba el correo del día antes que el bueno (#203), el
-- backend duplicado en el Debian, el add-on del Green resucitado. Con dos procesos, lo
-- que vive en memoria (WOL, órdenes de la casa, avisos al móvil) lo escribe uno y lo lee
-- el otro, sin un solo error. Ver «Gemelos» en backend/main.py.
--
-- Una fila por PROCESO, no por máquina: `instancia` es aleatoria en cada arranque. Crece
-- una fila por reinicio, que son pocas a la semana; no hace falta purga.
create table if not exists public.backend_latidos (
  instancia  text primary key,
  -- El SHA que sirve (GET / → version). Dos gemelos con el mismo commit son el caso que
  -- `version` sola no distinguía.
  version    text,
  -- Una pista de qué máquina es («Fly (…)», «add-on de Home Assistant», «host …»), para
  -- que el aviso diga cuál apagar. Nunca una IP.
  donde      text,
  arrancado  timestamptz not null,
  visto      timestamptz not null default now()
);

-- El vigilante pregunta siempre por lo mismo: quién ha latido desde hace un rato.
create index if not exists backend_latidos_visto_idx on public.backend_latidos (visto);

-- Como toda tabla del proyecto: RLS sin policies. Solo entra el backend, con la service
-- key, que la salta por diseño; la anon key (pública) no ve nada.
alter table public.backend_latidos enable row level security;

insert into public.migraciones_aplicadas (nombre) values ('20260924_backend_latidos')
  on conflict (nombre) do nothing;
