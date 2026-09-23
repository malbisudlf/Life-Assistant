-- Llamadas cotidianas: que el teléfono suene también por avisos del día a día.
--
-- Hasta aquí solo llamaba lo que se queda parado sin ti (una avería, un permiso). Mikel
-- pidió que llamara también por cosas como «llevas un día sin mandar datos», y eso se
-- decide regla a regla desde la zona dev. Ver `docs/LLAMADAS.md`.
--
-- `llamar` va en `avisos_reglas` porque es una propiedad de la regla, como `silenciada`.
-- Nace en false: una regla nueva no se pone a llamar sola por existir.
alter table public.avisos_reglas
  add column if not exists llamar boolean not null default false;

-- Una fila por llamada lanzada. Dos cosas en una:
--   * el TOPE diario se cuenta aquí (las averías no pasan por esta tabla, así que no lo
--     gastan);
--   * la clave es el id del aviso, y el 409 contra ella es lo que impide que un mismo
--     aviso llame dos veces si dos ticks se cruzan.
create table if not exists public.avisos_llamadas (
  aviso_id uuid        primary key,
  regla    text        not null,
  creado   timestamptz not null default now()
);

create index if not exists avisos_llamadas_creado on public.avisos_llamadas (creado);

alter table public.avisos_llamadas enable row level security;

-- Las que Mikel eligió el 2026-09-23. Las otras dos del catálogo (`al_salir`,
-- `pc_encendido`) quedan apagadas hasta que las encienda desde la zona dev.
insert into public.avisos_reglas (regla, llamar) values
  ('ingesta', true), ('reloj', true), ('salir', true), ('no_llegas', true),
  ('madrugon', true), ('malestar', true), ('hueco_entreno', true)
on conflict (regla) do update set llamar = excluded.llamar;

insert into public.migraciones_aplicadas (nombre) values ('20260923_llamadas_cotidianas')
  on conflict (nombre) do nothing;
