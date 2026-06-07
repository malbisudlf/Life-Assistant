-- Persistencia de tokens OAuth (Microsoft Graph) en Supabase.
-- Antes se guardaban en un archivo local del backend (.token), que se perdía
-- en cada redeploy de Fly.io al reconstruirse el filesystem del contenedor.
-- El backend accede con la service_role key; RLS activado sin policies para
-- que ningún cliente anon/authenticated pueda leer ni escribir esta tabla.

create table if not exists public.oauth_tokens (
  provider      text primary key,
  access_token  text not null,
  refresh_token text,
  expires_at    double precision not null,
  updated_at    timestamptz not null default now()
);

alter table public.oauth_tokens enable row level security;
