-- Una fila por informe semanal enviado, con la misma función que `brief_envios`:
-- hacer que "¿ya se ha mandado el de esta semana?" sea una pregunta ATÓMICA. El
-- disparador es el mismo tick de Home Assistant, que pasa cada 5 minutos, así que sin
-- la clave primaria bastaría con que dos ticks se solaparan para mandarlo dos veces.
--
-- Tabla aparte y no una columna en `brief_envios` a propósito, aunque la forma sea la
-- misma: si esta migración no se aplica, lo único que no funciona es el informe
-- semanal. Metiéndolo en `brief_envios` —cambiando su clave primaria para admitir dos
-- tipos de envío— una migración sin aplicar rompería el resumen DIARIO, que es el que
-- de verdad importa. Duplicar cinco líneas de esquema es más barato que eso.
create table if not exists public.informe_envios (
    -- Fecha del día en que se manda (el domingo, salvo que se cambie INFORME_DIA).
    fecha      date        primary key,
    enviado_at timestamptz not null default now()
);

-- Sin policies: solo entra el backend con la service key, que salta la RLS por diseño.
alter table public.informe_envios enable row level security;
