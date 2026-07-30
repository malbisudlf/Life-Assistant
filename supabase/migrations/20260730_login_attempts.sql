-- Intentos fallidos de login, para que el límite sobreviva a que Fly duerma la
-- máquina (auto_stop_machines) entre tandas. El contador vivía en memoria y se
-- borraba en cada cold start: un atacante solo tenía que esperar a que el backend
-- se durmiera para que el límite de intentos volviera a cero.
--
-- Es una tabla y no una fila con contador porque así el borrado del cerrojo
-- (la ventana de LOGIN_WINDOW_SECONDS) es "las filas más viejas que X", sin tener
-- que sincronizar un contador y su timestamp de inicio en dos escrituras.
create table if not exists public.login_attempts (
  id         uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now()
);
create index if not exists login_attempts_created_at_idx on public.login_attempts (created_at desc);
alter table public.login_attempts enable row level security;
