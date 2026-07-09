-- Esquema base para una instancia nueva de Life Assistant (kit self-hosted).
-- Las tablas de jobs/agentes/oauth_tokens tienen sus propias migraciones anteriores;
-- esta añade las que faltaban en el repo: ideas, entrenamiento y salud.
-- Todas se acceden SOLO desde el backend con la service key: RLS activado sin
-- policies para que ningún cliente anon/authenticated pueda tocarlas.

create extension if not exists pgcrypto;

-- Ideas por voz/texto (Whisper + GPT)
create table if not exists public.ideas (
  id         uuid primary key default gen_random_uuid(),
  key        text not null,          -- título corto extraído
  full_text  text not null,          -- resumen completo
  tag        text not null default 'idea',
  created_at timestamptz not null default now()
);
create index if not exists ideas_created_at_idx on public.ideas (created_at desc);
alter table public.ideas enable row level security;

-- Entrenamiento personal: cliente, sesiones y cobros
create table if not exists public.training_clients (
  id                   uuid primary key default gen_random_uuid(),
  name                 text,
  price_per_hour       numeric not null check (price_per_hour > 0),
  sessions_per_payment integer not null check (sessions_per_payment > 0),
  created_at           timestamptz not null default now()
);
alter table public.training_clients enable row level security;

create table if not exists public.training_sessions (
  id             uuid primary key default gen_random_uuid(),
  client_id      uuid not null references public.training_clients(id) on delete cascade,
  date           date not null,
  duration_hours numeric not null check (duration_hours > 0),
  created_at     timestamptz not null default now()
);
create index if not exists training_sessions_client_idx on public.training_sessions (client_id, created_at desc);
alter table public.training_sessions enable row level security;

create table if not exists public.training_payments (
  id         uuid primary key default gen_random_uuid(),
  client_id  uuid not null references public.training_clients(id) on delete cascade,
  date       date not null,
  amount     numeric not null,
  created_at timestamptz not null default now()
);
create index if not exists training_payments_client_idx on public.training_payments (client_id, created_at desc);
alter table public.training_payments enable row level security;

-- Métricas de salud (Apple Watch via Health Auto Export / iOS Shortcuts).
-- La unicidad (metric_date, metric_name) es la que produce el 409 que el backend
-- resuelve con PATCH (patrón POST → si 409, PATCH). No la quites.
create table if not exists public.health_metrics (
  id          uuid primary key default gen_random_uuid(),
  metric_date date not null,
  metric_name text not null,
  value       double precision,
  unit        text,
  extra       jsonb,
  created_at  timestamptz not null default now(),
  unique (metric_date, metric_name)
);
create index if not exists health_metrics_date_idx on public.health_metrics (metric_date desc);
alter table public.health_metrics enable row level security;
