-- El registro de qué migraciones se han aplicado de verdad.
--
-- Aquí no hay tooling de migraciones: se pegan a mano en el editor SQL de Supabase, y
-- eso significa que se olvidan. `20260824_salud_ajustes` estuvo un mes sin aplicar, con
-- `PATCH /health/ajustes` devolviendo 502 y la copia de seguridad muriendo entera al
-- llegar a esa tabla, y nadie lo supo hasta que alguien fue a mirar. La pestaña Base de
-- datos de la zona dev (docs/ZONA_DEV.md) existe para que eso se vea el mismo día.
--
-- Por qué una tabla y no sondear el esquema: sondear hay que mantenerlo a mano —un mapa
-- de migración a tabla o columna— y una migración nueva sin entrada en ese mapa pasaría
-- desapercibida, que es exactamente el fallo que esto viene a evitar. Aquí la lista de lo
-- ESPERADO sale del propio repositorio y la de lo APLICADO de esta tabla: ninguna de las
-- dos se mantiene a mano.
--
-- LA CONVENCIÓN, a partir de aquí: **toda migración nueva termina insertando su nombre**
-- en esta tabla. Dos líneas al final del fichero:
--
--     insert into public.migraciones_aplicadas (nombre) values ('20261015_lo_que_sea')
--       on conflict (nombre) do nothing;
--
-- Sin esa línea, la migración se aplicará y la zona dev seguirá diciendo que falta — que
-- es mejor error que el contrario, pero error igual.
create table if not exists public.migraciones_aplicadas (
    -- El nombre del fichero SIN extensión, tal cual está en supabase/migrations/.
    nombre     text        primary key,
    aplicada   timestamptz not null default now()
);

-- Sin policies, como todas: solo entra el backend con la service key, que salta la RLS
-- por diseño. Sin esta línea, la anon key (pública) abriría la tabla al REST de Supabase
-- desde internet.
alter table public.migraciones_aplicadas enable row level security;

-- Las que ya estaban puestas el 2026-09-10, declaradas de una vez. Ejecutar esto es
-- afirmar que están aplicadas: si alguna no lo estuviera, esta tabla mentiría y la
-- pestaña la daría por buena. Se dan por buenas porque el backend las usa a diario y
-- llevaría meses roto si faltara alguna — salvo las dos de ETF, que son de septiembre y
-- se comprobaron a mano al escribir esto.
insert into public.migraciones_aplicadas (nombre) values
    ('20260508_jobs_queue'),
    ('20260511_job_events'),
    ('20260511_job_results'),
    ('20260607_oauth_tokens'),
    ('20260707_esquema_base'),
    ('20260724_clothing'),
    ('20260729_rls_jobs'),
    ('20260730_login_attempts'),
    ('20260802_app_logs'),
    ('20260804_brief_envios'),
    ('20260804_presence'),
    ('20260807_jarvis_memoria'),
    ('20260808_ha_entidades'),
    ('20260808_jarvis_mcp_servidores'),
    ('20260808_jarvis_recordatorios'),
    ('20260813_brief_ajustes'),
    ('20260816_brief_instantanea'),
    ('20260816_health_fuente'),
    ('20260816_informe_envios'),
    ('20260817_vigilante_estado'),
    ('20260818_avisos_gobierno'),
    ('20260819_vigilancias'),
    ('20260820_reglas_usuario'),
    ('20260820_revision_hallazgos'),
    ('20260824_etf_aportaciones_hora'),
    ('20260824_etf_cartera'),
    ('20260824_salud_ajustes'),
    ('20260830_avisos_entidades'),
    ('20260831_averias'),
    ('20260903_avisos_motivo'),
    ('20260903_gasto_modelo'),
    ('20260904_sesion_avisos'),
    ('20260909_alarmas'),
    ('20260909_alarmas_repeticion'),
    ('20260909_ideas_dev'),
    ('20260910_migraciones_aplicadas')
on conflict (nombre) do nothing;
