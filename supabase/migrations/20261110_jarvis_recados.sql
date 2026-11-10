-- Los recados: un asunto con otra persona que Jarvis lleva hasta cerrarlo, llamando varias
-- veces y varios días. Ver «RECADOS» en `backend/main.py` y `docs/RECADOS.md`.
--
-- En una tabla y no en memoria, como las llamadas sueltas: un recado dura días, y el
-- backend se despliega varias veces en ese tiempo.
create table if not exists public.jarvis_recados (
  id             uuid primary key,
  -- El recado en pocas palabras («cita dentista»), para nombrarlo en los avisos.
  asunto         text not null,
  -- El nombre del contacto tal como está guardado. Nunca un número: el teléfono se busca
  -- en los contactos en cada llamada, como en `llamar_a_alguien`.
  contacto       text not null,
  mensaje        text not null,
  objetivo       text not null,
  contexto       text not null default '',
  -- activo (esperando su siguiente llamada), llamando, preguntando (te ha preguntado si
  -- vuelve a llamar), hecho, abandonado.
  estado         text not null default 'activo',
  intentos       integer not null default 0,
  max_intentos   integer not null default 4,
  -- Si se llama también en fin de semana (un amigo sí, una clínica no).
  finde          boolean not null default false,
  -- Si insiste sin preguntarte antes de cada nueva llamada.
  autonomo       boolean not null default false,
  -- Si se encargó por teléfono: al cerrarse una llamada con conversación, te llama.
  devolver       boolean not null default false,
  proximo        timestamptz,
  caduca         timestamptz not null,
  ultimo_intento timestamptz,
  -- La pregunta «¿vuelvo a llamar?» que está en el aire (`jarvis_preguntas.id`).
  pregunta       uuid,
  preguntado     timestamptz,
  -- Lo que pasó en cada intento: [{cuando, que}]. Sale de lo que dijo otra persona.
  historial      jsonb not null default '[]'::jsonb,
  resultado      text not null default '',
  creado         timestamptz not null default now(),
  actualizado    timestamptz not null default now()
);

-- El reloj pregunta cada pocos minutos por los abiertos.
create index if not exists jarvis_recados_estado on public.jarvis_recados (estado, proximo);

-- Sin policies: solo entra el backend con la service key, que salta RLS por diseño.
alter table public.jarvis_recados enable row level security;

insert into public.migraciones_aplicadas (nombre) values ('20261110_jarvis_recados')
  on conflict (nombre) do nothing;
