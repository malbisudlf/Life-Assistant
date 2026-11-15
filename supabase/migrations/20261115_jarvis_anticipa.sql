-- Jarvis que se anticipa, fase 1 (docs/JARVIS_ANTICIPA.md): el registro de lo que Mikel
-- pide de una lista cerrada de acciones de bajo riesgo, los patrones que salen de ahí con
-- su confianza, y el acuse de cada borrado. Ver «JARVIS QUE SE ANTICIPA» en
-- `backend/main.py` y la lógica en `backend/anticipa.py`.
--
-- Lo que NO hay en ninguna de las tres: texto de conversaciones, de WhatsApp, de correo ni
-- de páginas. Solo la herramienta, sus argumentos declarados, cuándo y en qué lugar (la
-- categoría: casa, gimnasio, uni, coche o fuera; nunca coordenadas).

create table if not exists public.jarvis_eventos (
  id           uuid primary key default gen_random_uuid(),
  ts           timestamptz not null,
  -- El día y el minuto LOCALES, ya calculados: los patrones son de «los lunes a las 9» de
  -- Mikel, no de UTC, y así un cambio de hora no los mueve.
  dia          date not null,
  minuto       smallint not null check (minuto between 0 and 1439),
  dia_semana   smallint not null check (dia_semana between 0 and 6),
  ubicacion    text not null check (ubicacion in ('casa', 'gimnasio', 'uni', 'coche', 'fuera')),
  -- peticion: lo pidió él. sugerencia: se lo propuso Jarvis, y `respuesta` dice qué contestó.
  tipo         text not null check (tipo in ('peticion', 'sugerencia')),
  -- La clave que agrupa «lo mismo»: herramienta + huella de sus argumentos.
  accion       text not null,
  herramienta  text not null,
  argumentos   jsonb not null default '{}'::jsonb,
  -- Por dónde habló. No existe ningún valor para lo ajeno: lo que no viene de una boca de
  -- Mikel no entra.
  origen       text not null check (origen in ('chat', 'voz', 'telefono', 'telegram', 'atajo',
                                               'dashboard', 'sugerencia')),
  respuesta    text check (respuesta in ('si', 'no', 'ignorada')),
  -- En una sugerencia: el patrón que la originó y la pregunta del móvil que la lleva.
  patron       text,
  pregunta     uuid
);

create index if not exists jarvis_eventos_dia_idx on public.jarvis_eventos (dia desc);
create index if not exists jarvis_eventos_pregunta_idx on public.jarvis_eventos (pregunta)
  where pregunta is not null;

create table if not exists public.jarvis_patrones (
  -- accion@grupo@ubicacion. `grupo` es cada_dia, laborables, finde o d0..d6.
  clave             text primary key,
  accion            text not null,
  herramienta       text not null,
  argumentos        jsonb not null default '{}'::jsonb,
  grupo             text not null,
  minuto            smallint not null,
  ubicacion         text not null,
  ocurrencias       integer not null,
  dias_posibles     integer not null,
  proporcion        real not null,
  confianza         real not null,
  ultima_vez        date,
  -- Hasta qué día se ha repasado la confianza (el decaimiento no se aplica dos veces).
  repasado          date not null,
  ultima_sugerencia timestamptz,
  creado            timestamptz not null default now()
);

-- El acuse de cada borrado: cuándo y cuántos, nunca qué. Es lo único que sobrevive a
-- «bórralo todo», y es lo que lo hace verificable.
create table if not exists public.jarvis_anticipa_borrados (
  id        uuid primary key default gen_random_uuid(),
  ts        timestamptz not null default now(),
  que       text not null,
  eventos   integer not null,
  patrones  integer not null,
  quedan    integer not null
);

alter table public.jarvis_eventos           enable row level security;
alter table public.jarvis_patrones          enable row level security;
alter table public.jarvis_anticipa_borrados enable row level security;

insert into public.migraciones_aplicadas (nombre) values ('20261115_jarvis_anticipa')
  on conflict (nombre) do nothing;
