-- Memoria del vigilante del sistema: desde cuándo pasa cada avería, cuántas veces
-- lleva vista y si ya se abrió un issue por ella.
--
-- Tabla propia y no una columna en otro sitio, por lo mismo que `informe_envios`: si
-- esta migración no se aplica, lo único que se degrada es el vigilante — sigue
-- detectando y avisando, pero sin las cifras y sin abrir issues. Nada de lo que hay
-- encima (el resumen diario, los recordatorios) se entera.
--
-- `veces` es lo que impide que un parche esconda una avería: un fallo que se repara
-- solo todos los días no está arreglado, y el aviso lo dice contando las veces.
create table if not exists public.vigilante_estado (
  clave       text primary key,
  primera_vez timestamptz not null default now(),
  ultima_vez  timestamptz not null default now(),
  veces       integer     not null default 1,
  -- URL del issue abierto por esta avería. Mientras no sea null no se abre otro: uno
  -- por día del mismo fallo convertiría el repo en el ruido del que esto viene a salvar.
  issue_url   text
);

-- Como todas las tablas del proyecto: solo entra el backend con la service key, que
-- salta la RLS por diseño. Sin esto, la anon key (pública) daría acceso desde internet.
alter table public.vigilante_estado enable row level security;
