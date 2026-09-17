-- Las dos fuentes que le faltaban a la línea del día. Hasta aquí, sus carriles de
-- «Presencia» y «Casa» no podían dibujar nada: el primero solo tenía el total diario
-- (`health_metrics.time_at_home`) y el segundo no tenía absolutamente nada, porque la
-- cola de órdenes vive en memoria y se vacía en cuanto Home Assistant se la lleva.

-- Tramos de presencia. Esto REVIERTE en parte la decisión de `docs/IDEAS.md` («un
-- histórico de presencia: es el dato más sensible del proyecto»), y conviene saber en
-- qué parte: lo que se guarda es el CUÁNDO, nunca el DÓNDE. Aquí no hay zonas, ni
-- coordenadas, ni nombres de sitio — solo un booleano y dos horas. «De 08:15 a 13:40,
-- fuera» no dice dónde estabas, y es lo único que el carril necesita para dibujarse.
--
-- Y se purga: `PRESENCIA_TRAMOS_DIAS` (35 por defecto, lo que cubre la línea del día
-- más un margen). Un histórico que solo crece acaba siendo un histórico de años, y de
-- este dato en concreto no hace falta ninguno.
create table if not exists public.presencia_tramos (
  id      uuid primary key default gen_random_uuid(),
  -- El día LOCAL al que pertenece el tramo. Un tramo que cruza la medianoche se parte
  -- en dos filas, por lo mismo que se parte para el total diario: si no, la noche
  -- entera se imputa al día en que empezó.
  dia     date not null,
  desde   timestamptz not null,
  hasta   timestamptz not null,
  en_casa boolean not null
);

-- El carril pregunta siempre por lo mismo: los tramos de un día, en orden.
create index if not exists presencia_tramos_dia_idx on public.presencia_tramos (dia, desde);

-- Acciones de la casa. `_ha_ordenes` es una lista en memoria que `/ha/ordenes-pending`
-- VACÍA al servirla: está bien para lo suyo (una orden perdida en un reinicio solo
-- cuesta volver a pulsar el botón) pero significa que, en cuanto HA se lleva la orden,
-- no queda constancia de que existió. Esto es la constancia, y es solo para mirar:
-- nadie la lee para decidir nada.
create table if not exists public.casa_acciones (
  id       uuid primary key default gen_random_uuid(),
  dia      date not null,
  momento  timestamptz not null default now(),
  servicio text not null,
  entidad  text not null,
  -- Quién la mandó: 'jarvis', 'alarma', 'regla'... Para poder leer el carril sin
  -- adivinar por qué se encendió una luz a las seis de la mañana.
  origen   text
);

create index if not exists casa_acciones_dia_idx on public.casa_acciones (dia, momento);

-- Sin policies: solo entra el backend con la service key, que salta RLS por diseño. Sin
-- esto, la anon key (pública) abriría las tablas al REST de Supabase desde internet — y
-- estas dos son, de largo, las que menos convienen abiertas.
alter table public.presencia_tramos enable row level security;
alter table public.casa_acciones    enable row level security;

insert into public.migraciones_aplicadas (nombre) values ('20260917_linea_del_dia')
  on conflict (nombre) do nothing;
