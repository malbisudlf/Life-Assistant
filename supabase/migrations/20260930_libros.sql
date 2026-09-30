-- Libros leídos (widget «Libros»): una fila por lectura, con su fecha de inicio y de
-- fin. `terminado` a null con `empezado` puesto = lo estás leyendo; los dos a null =
-- pendiente. Solo accesible desde el backend con la service key: RLS sin policies.
create table if not exists public.libros (
  id         uuid primary key default gen_random_uuid(),
  titulo     text not null check (length(btrim(titulo)) > 0),
  autor      text,
  portada    text,                                   -- URL de la portada (Open Library), opcional
  empezado   date,
  terminado  date,
  created_at timestamptz not null default now(),
  check (terminado is null or empezado is null or terminado >= empezado)
);
create index if not exists libros_created_at_idx on public.libros (created_at desc);
create index if not exists libros_titulo_idx on public.libros (lower(titulo));
alter table public.libros enable row level security;

insert into public.migraciones_aplicadas (nombre) values ('20260930_libros')
  on conflict (nombre) do nothing;
