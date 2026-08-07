-- Memoria persistente de Jarvis: hechos destilados de las conversaciones (preferencias,
-- objetivos, nombres, decisiones), no el historial — ese sigue viviendo en el cliente y
-- el backend no guarda conversaciones. Una fila por clave: `recordar` sobrescribe
-- (upsert con on_conflict=clave) y `olvidar` borra.
create table if not exists public.jarvis_memoria (
  clave       text primary key,
  contenido   text not null,
  updated_at  timestamptz not null default now()
);

-- Como el resto de tablas: RLS sin policies. Solo entra el backend con la service key,
-- que la salta por diseño; sin esto, la anon key daría acceso desde internet.
alter table public.jarvis_memoria enable row level security;
