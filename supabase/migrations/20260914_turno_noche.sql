-- El turno de noche: lo que el asistente resuelve mientras duermes, para que por la
-- mañana solo tengas que aprobarlo.
--
-- Dos tablas y no una a propósito. `noche_partes` existe para poder preguntar «¿ya se ha
-- hecho el turno de esta noche?» de forma ATÓMICA: la fecha es la clave primaria, así que
-- el segundo tick de la misma madrugada choca con un 409 y se va. Es el mismo truco que
-- `brief_envios`, y es lo que impide que dos ticks separados por cinco minutos redacten
-- los mismos borradores dos veces. Si el parte fuera una fila más de `noche_items` no
-- habría contra qué chocar.
--
-- Lo que NO entra aquí: el cuerpo de ningún correo. En `noche_items` va el asunto, el
-- remitente y el borrador redactado; el original se lee del buzón, se usa y se olvida.

create table if not exists public.noche_partes (
  fecha     date primary key,
  creado_at timestamptz not null default now(),
  -- Las cuentas del parte ({correos: 12, borradores: 4, ...}) para poder contarlo sin
  -- traerse los items.
  resumen   jsonb
);

create table if not exists public.noche_items (
  id        uuid primary key default gen_random_uuid(),
  fecha     date not null references public.noche_partes(fecha) on delete cascade,
  -- 'correo' | 'codigo' | 'agenda' | 'recado'
  area      text not null,
  titulo    text not null,
  detalle   text,
  enlace    text,
  -- pendiente → aprobado | descartado. «Aprobado» aquí significa «visto y me vale», no
  -- «enviado»: el turno de noche no tiene camino de envío.
  estado    text not null default 'pendiente',
  datos     jsonb,
  creado_at timestamptz not null default now()
);

-- El parte de la mañana pregunta siempre por lo mismo: los items de un día.
create index if not exists noche_items_fecha_idx on public.noche_items (fecha);

-- Sin policies: solo entra el backend con la service key, que salta RLS por diseño. Sin
-- esto, la anon key (pública) abriría la tabla al REST de Supabase desde internet.
alter table public.noche_partes enable row level security;
alter table public.noche_items  enable row level security;

insert into public.migraciones_aplicadas (nombre) values ('20260914_turno_noche')
  on conflict (nombre) do nothing;
