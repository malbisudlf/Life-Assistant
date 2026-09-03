-- Por qué te dije eso: los números crudos que dispararon cada aviso.
--
-- Hasta aquí un aviso era una frase redactada por un modelo, y cuando se equivocaba no
-- había forma de reconstruir de dónde había salido. La señal de utilidad
-- (`avisos_reglas`) dice QUÉ reglas se ignoran; esto dice POR QUÉ fallan, que es lo
-- único que permite arreglarlas en vez de silenciarlas.
--
-- **Tabla propia y no una columna en `jarvis_recordatorios`**, por lo mismo que
-- `informe_envios` y `vigilante_estado`: si esta migración no se aplica, lo único que
-- se pierde es la explicación. Una columna nueva en la tabla de avisos haría que un
-- insert con ese campo devolviera 400 mientras la migración no estuviera puesta — es
-- decir, dejaría al sistema entero SIN AVISOS por añadir una función de diagnóstico.
--
-- Se guardan los NÚMEROS, no la frase: la frase ya está en el aviso. Lo que no se puede
-- reconstruir después es contra qué se comparó y con cuántos datos detrás.
create table if not exists public.avisos_motivos (
  aviso_id uuid        primary key,
  regla    text        not null,
  datos    jsonb       not null,
  creado   timestamptz not null default now()
);

create index if not exists avisos_motivos_regla on public.avisos_motivos (regla, creado desc);

-- Como todas las tablas del proyecto: solo entra el backend con la service key, que
-- salta la RLS por diseño. Sin esto, la anon key (pública) daría acceso desde internet.
alter table public.avisos_motivos enable row level security;
