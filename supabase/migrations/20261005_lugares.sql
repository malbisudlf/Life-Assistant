-- Lugares: que Jarvis sepa si estás en casa, en el gimnasio o en la uni antes de hablar.
-- Ver «Lugares» en `backend/main.py` y en `docs/JARVIS.md`.

-- 1. La CATEGORÍA del sitio en los tramos de presencia. Esto mueve un paso la frontera de
-- `20260917_linea_del_dia` («se guarda el CUÁNDO, nunca el DÓNDE»), y conviene saber
-- cuánto: solo se escribe `gimnasio` o `uni`, y solo si la zona de HA está declarada como
-- tal (`ZONAS_GIMNASIO`, `ZONAS_UNI`). Ni el nombre de la zona, ni coordenadas, ni ningún
-- sitio que no hayas declarado tú: cualquier otro «fuera» sigue siendo `null`. Hace falta
-- para no regañarte por no entrenar el día que has ido al gimnasio y para dibujarlo en la
-- línea del día. Se purga con el resto del tramo (`PRESENCIA_TRAMOS_DIAS`).
--
-- Sin esta columna el backend sigue funcionando: escribe y lee los tramos sin lugar y
-- deja un error en el registro diciendo que falta esta migración.
alter table public.presencia_tramos add column if not exists lugar text
  check (lugar is null or lugar in ('gimnasio', 'uni'));

-- 2. Recordatorios por lugar: «recuérdame al llegar a casa…», «…al salir del gimnasio».
-- Tabla aparte y no `jarvis_recordatorios` porque no tienen hora: el despachador pregunta
-- por `cuando`, y uno sin hora (o con una inventada) se mezclaría con todo lo que mira esa
-- tabla. Al dispararse se convierte en un recordatorio normal de los de siempre.
create table if not exists public.recordatorios_lugar (
  id           uuid primary key default gen_random_uuid(),
  texto        text not null,
  lugar        text not null check (lugar in ('casa', 'gimnasio', 'uni')),
  momento      text not null default 'llegar' check (momento in ('llegar', 'salir')),
  creado       timestamptz not null default now(),
  -- La reserva: un PATCH condicional sobre `disparado_at is null`, como el despacho.
  disparado_at timestamptz
);

-- Al llegar o al salir se pregunta siempre lo mismo: los pendientes de ese sitio.
create index if not exists recordatorios_lugar_pendientes
  on public.recordatorios_lugar (lugar, momento) where disparado_at is null;

-- Sin policies: solo entra el backend con la service key, que salta RLS por diseño.
alter table public.recordatorios_lugar enable row level security;

insert into public.migraciones_aplicadas (nombre) values ('20261005_lugares')
  on conflict (nombre) do nothing;
