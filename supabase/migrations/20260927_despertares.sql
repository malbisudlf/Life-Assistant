-- La primera señal de despertar de cada día, para que el teléfono sepa si puede sonar.
--
-- El 2026-09-27 Jarvis llamó a las 07:00 por una avería de madrugada: «ya no es de
-- noche» se tomaba por «estás despierto». Desde aquí el teléfono solo suena cuando
-- consta que te has despertado (el Atajo del cargador, la alarma de respaldo confirmada
-- o decírselo a Jarvis), o pasada la hora de respaldo. Ver `docs/LLAMADAS.md`, «Solo
-- cuando estás despierto».
--
-- Va en una tabla propia y no se lee de `brief_envios` porque el resumen diario CONSUME
-- la señal: la olvida al mandar el correo, no la ve si está pausado y la del cargador le
-- llega cinco minutos tarde. Aquí se guarda la señal tal cual, una fila por día.
--
-- Si esta migración no se aplica, el backend sigue funcionando con la copia en memoria:
-- lo único que se pierde es la señal de hoy tras un reinicio, y entonces el teléfono
-- espera a la hora de respaldo (`LLAMADAS_SIN_SENAL_DESDE`).
create table if not exists public.despertares (
  -- El día LOCAL de la señal. La clave es lo que hace que solo cuente la primera: la
  -- segunda del día choca con un 409 y el backend lo da por bueno.
  fecha            date        primary key,
  primera_senal_at timestamptz not null,
  -- Quién lo dijo («despertar», «alarma», «jarvis»…), ya limpio y recortado a 40.
  fuente           text        not null default '',
  creado           timestamptz not null default now()
);

-- Como toda tabla del proyecto: RLS sin policies. Solo entra el backend, con la service
-- key, que la salta por diseño; la anon key (pública) no ve nada.
alter table public.despertares enable row level security;

insert into public.migraciones_aplicadas (nombre) values ('20260927_despertares')
  on conflict (nombre) do nothing;
