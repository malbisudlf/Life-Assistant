-- Las preguntas que Jarvis te manda al móvil con botones, y lo que contestas. Ver
-- «Preguntas de Jarvis al móvil» en `backend/main.py` y en `docs/JARVIS.md`.
--
-- Tabla aparte y no columnas en `jarvis_recordatorios`: mientras esta migración no esté
-- aplicada, lo único que falla es mandar una pregunta con opciones (la herramienta lo
-- dice); con columnas nuevas allí, fallaría el insert de todos los avisos del sistema.
create table if not exists public.jarvis_preguntas (
  -- También es el `tag` de la notificación y va dentro del id de cada botón.
  id            uuid primary key,
  texto         text not null,
  -- Las respuestas posibles, en el orden de los botones: `resp1-` es la primera.
  opciones      jsonb not null default '[]'::jsonb,
  -- null hasta que pulsas. La primera respuesta es la que vale: el PATCH del botón es
  -- condicional (`respuesta=is.null`).
  respuesta     text,
  respondido_at timestamptz,
  creado        timestamptz not null default now()
);

-- `respuesta_notificacion` sin id lee la más reciente.
create index if not exists jarvis_preguntas_creado on public.jarvis_preguntas (creado desc);

-- Sin policies: solo entra el backend con la service key, que salta RLS por diseño.
alter table public.jarvis_preguntas enable row level security;

insert into public.migraciones_aplicadas (nombre) values ('20261011_jarvis_preguntas')
  on conflict (nombre) do nothing;
