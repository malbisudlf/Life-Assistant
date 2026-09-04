-- Lo que una sesión de Claude Code deja dicho para que puedas contestarle.
--
-- El canal ya existía y solo sabía hablar de UNA cosa: el permiso de despliegue
-- (`docs/AVERIAS.md`). Esto es lo que hace que por ese mismo canal quepa cualquier otra:
-- una sesión que acaba de trabajar en el repositorio deja aquí «esto me pediste, esto he
-- hecho, esto ha quedado a medias», el aviso llega al móvil y al descolgar Jarvis ya lo
-- sabe sin ir a buscarlo (ver `docs/AVISAME.md`).
--
-- Tabla nueva y no una columna más en `revision_hallazgos` —que es donde vive el permiso
-- de despliegue— porque no es la misma pregunta: aquella tiene dos respuestas cerradas
-- (desplegar o no) y un PR concreto detrás; ésta tiene una respuesta en lenguaje natural
-- que dispara una sesión nueva. Compartir tabla obligaría a que la mitad de las columnas
-- estuvieran siempre vacías y a que el PATCH condicional de una entendiera los estados
-- de la otra.
--
-- `id` es el mismo con el que se apunta el aviso en `jarvis_recordatorios`, igual que en
-- la revisión: así el botón de la notificación no necesita llevar nada más que su id.
create table if not exists public.sesion_avisos (
  id          uuid        primary key,
  -- Una línea para la notificación. Lo demás no cabe en un aviso del móvil
  -- (`RECORDATORIO_MAX_TEXTO` son 200 caracteres) y por eso vive aquí.
  titulo      text        not null,
  -- El contexto que se le lee a Jarvis al descolgar. Lo escribe un modelo y acaba dentro
  -- del prompt de otro modelo que tiene herramientas: se guarda tal cual y se delimita
  -- como DATO al usarlo, igual que el enunciado de Alud (decisión 4 de docs/AVISAME.md).
  pedido      text,
  hecho       text,
  pendiente   text,
  -- Adónde ir a mirar: el PR, la rama, la sesión. Array y no texto para que el frontend
  -- pueda enlazarlos sin parsear una lista escrita a mano.
  enlaces     text[],
  -- Si la sesión se quedó PARADA hasta que contestes. Es lo único que decide que el
  -- aviso atraviese el silencio del móvil (decisión 2): un «ya está hecho» espera a que
  -- mires, un «no puedo seguir sin ti» no.
  bloqueado   boolean     not null default false,
  -- pendiente → visto | contestado | caducado. Sin constraint que los liste, igual que
  -- en `revision_hallazgos`: quien los valida es el PATCH condicional, no el esquema.
  estado      text        not null default 'pendiente',
  -- Lo que dijiste, y la sesión nueva que se disparó con ello. Los rellena la fase 3.
  respuesta   text,
  sesion_url  text,
  respondido  timestamptz,
  creado      timestamptz not null default now()
);

-- La única consulta que se hace: qué hay esperando respuesta, lo más reciente primero
-- (`GET /llamada/pendiente`).
create index if not exists sesion_avisos_pendientes
  on public.sesion_avisos (estado, creado desc);

-- Solo entra el backend con la service key, que salta RLS por diseño. Sin esto, la anon
-- key (pública) daría acceso al REST de Supabase desde internet.
alter table public.sesion_avisos enable row level security;
