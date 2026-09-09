-- Alarmas de respaldo: el despertador lo pones donde quieras (el iPhone, normalmente),
-- y esto es la red que hay debajo. A la hora apuntada llega un aviso al móvil con un
-- botón; si no lo pulsas, se escala a la casa y se insiste hasta que confirmes.
--
-- Tabla propia y no una fila más en `jarvis_recordatorios` a propósito: un recordatorio
-- se manda una vez y se acabó, y una alarma es una MÁQUINA DE ESTADOS que insiste,
-- cuenta intentos y se rinde. Meterla en la misma tabla habría obligado a que el
-- despachador de recordatorios distinguiera dos cosas que solo se parecen en que tienen
-- hora.

create table if not exists public.alarmas (
  id            uuid primary key default gen_random_uuid(),
  cuando        timestamptz not null,
  etiqueta      text,
  -- armada → avisada → escalada → confirmada | rendida | cancelada
  estado        text not null default 'armada',
  intentos      integer not null default 0,
  avisado_at    timestamptz,
  escalado_at   timestamptz,
  confirmado_at timestamptz,
  creado        timestamptz not null default now()
);

-- El tick pregunta siempre por lo mismo: qué hay vivo y con qué hora.
create index if not exists alarmas_activas on public.alarmas (estado, cuando);

-- Sin policies: solo entra el backend con la service key, que salta RLS por diseño. Sin
-- esto, la anon key (pública) abriría la tabla al REST de Supabase desde internet.
alter table public.alarmas enable row level security;
