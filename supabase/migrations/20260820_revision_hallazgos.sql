-- La decisión sobre los hallazgos de la revisión nocturna.
--
-- De madrugada, una sesión de Claude Code revisa los commits del día y abre un issue.
-- El aviso que lo cuenta lleva dos botones —«Arreglarlo» y «No hacer nada»—, y entre
-- que sale (08:30) y se pulsa pueden pasar horas: la máquina de Fly se duerme por el
-- camino, así que un mapa en memoria de id → issue no llegaría vivo al toque del botón.
-- Por eso la decisión vive aquí, igual que los recordatorios.
--
-- `id` NO es aleatorio: es el uuid5 del número del issue (`_uuid_revision`), y es el
-- mismo id con el que se apunta el aviso en `jarvis_recordatorios`. Dos cosas a cambio:
-- el botón de la notificación no necesita llevar nada más que su propio id, y un
-- reintento del workflow choca contra esta clave primaria en vez de abrir un segundo
-- aviso del mismo issue — el 409 es la pregunta atómica de siempre.
--
-- `estado` es lo que impide que dos toques seguidos lancen dos agentes: la transición se
-- hace con un PATCH condicional (`estado=eq.pendiente`), no con un GET y luego un UPDATE.
create table if not exists public.revision_hallazgos (
  id            uuid        primary key,
  issue_numero  integer     not null,
  issue_titulo  text,
  issue_url     text,
  -- pendiente → arreglando | descartado. Si el disparo del arreglo falla, vuelve a
  -- pendiente: una decisión consumida sin efecto deja el botón muerto y el issue sin
  -- arreglar, que es el peor de los dos errores posibles.
  estado        text        not null default 'pendiente',
  -- La sesión que se lanzó a arreglarlo, para poder ir a mirarla.
  sesion_url    text,
  decidido_at   timestamptz,
  creado        timestamptz not null default now()
);

-- Jarvis pregunta siempre lo mismo: qué queda por decidir, lo más reciente primero.
create index if not exists revision_hallazgos_pendientes
  on public.revision_hallazgos (estado, creado desc);

-- Solo entra el backend con la service key, que salta RLS por diseño. Sin esto, la anon
-- key (pública) daría acceso al REST de Supabase desde internet.
alter table public.revision_hallazgos enable row level security;
