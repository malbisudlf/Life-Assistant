-- La salud de otras personas (la familia): sus datos del Apple Watch/iPhone, con la
-- misma forma que `health_metrics` pero en una tabla APARTE, con la persona en cada fila.
--
-- Tabla aparte y no una columna `persona` en `health_metrics` a propósito: esa tabla la
-- leen decenas de sitios del backend (el resumen diario, Jarvis, las reglas, el
-- diagnóstico, el dashboard) y ninguno filtra por persona, porque hasta hoy solo había
-- una. Con una columna, bastaba olvidar el filtro en UNA de esas lecturas para que la
-- salud de otra persona acabara en el briefing de Mikel. Con otra tabla, ninguna lectura
-- de lo suyo puede verla aunque se olvide de algo. Ver docs/SALUD_FAMILIA.md.
create table if not exists public.salud_familia (
    id          uuid        primary key default gen_random_uuid(),
    -- El identificador corto de la persona (`SALUD_FAMILIA` en el backend.env). Lo pone
    -- el backend a partir del TOKEN con el que llega el envío, nunca del cuerpo.
    persona     text        not null,
    metric_date date        not null,
    metric_name text        not null,
    value       numeric,
    unit        text,
    extra       jsonb,
    fuente      text,
    created_at  timestamptz not null default now(),
    -- La unicidad real, contra la que resuelve el upsert (`on_conflict=` en el backend).
    unique (persona, metric_date, metric_name)
);

-- Una fila por persona y día con briefing ya enviado: hace ATÓMICA la pregunta «¿ya le ha
-- llegado el de hoy?», igual que `brief_envios`. Si la rutina de su Claude se lanza dos
-- veces, el segundo correo se encuentra el 409 de la clave primaria y no sale.
create table if not exists public.salud_familia_envios (
    persona    text        not null,
    fecha      date        not null,
    enviado_at timestamptz not null default now(),
    primary key (persona, fecha)
);

-- Sin policies: solo entra el backend con la service key, que salta la RLS por diseño.
-- Son datos de salud de otras personas: con la anon key (pública por diseño) y sin RLS,
-- cualquiera podría leerlos desde internet.
alter table public.salud_familia        enable row level security;
alter table public.salud_familia_envios enable row level security;

insert into public.migraciones_aplicadas (nombre) values ('20261015_salud_familia')
  on conflict (nombre) do nothing;
