-- Páginas que Jarvis vigila por ti.
--
-- Es la capacidad proactiva GENÉRICA: en vez de una regla nueva en el código por cada
-- cosa que quieras vigilar (un precio, una plaza que se libera, una nota que se publica,
-- un horario que cambia), una que las cubre todas y que se crea hablando.
--
-- Va a una tabla y no a memoria por lo de siempre: Fly escala a cero. Y el reloj lo pone
-- el sondeo de Home Assistant, como todo lo demás que pasa sin que nadie abra el
-- dashboard.
create table if not exists public.vigilancias (
  id          uuid        primary key default gen_random_uuid(),
  clave       text        not null unique,   -- nombre corto: con él se cancela
  url         text        not null,
  -- Qué se considera novedad. NULL = cualquier cambio del contenido; si lleva texto, se
  -- avisa cuando ESE texto aparece. Son dos preguntas distintas ("¿ha cambiado algo?" y
  -- "¿ya está disponible?") y mezclarlas daría avisos por cualquier cosa.
  buscar      text,
  -- Hash del contenido de la última visita. Sin él, la primera revisión avisaría siempre.
  huella      text,
  creada      timestamptz not null default now(),
  ultima_vez  timestamptz,
  avisos      integer     not null default 0
);

alter table public.vigilancias enable row level security;
