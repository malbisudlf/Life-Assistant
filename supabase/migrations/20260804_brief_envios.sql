-- Una fila por día en que se ha mandado el resumen diario.
--
-- Existe por una sola razón: hacer que "¿ya se ha enviado hoy?" sea una pregunta
-- ATÓMICA. Al correo lo disparan ahora varias fuentes independientes (la señal de
-- despertar del móvil, la llegada del sueño del Watch, el sondeo de Home Assistant y
-- el workflow de GitHub como red de seguridad), y cualquier par de ellas puede
-- coincidir en el mismo minuto. Con un GET previo para comprobarlo, dos disparadores
-- simultáneos leen los dos "no enviado" y mandan dos correos; con `fecha` como clave
-- primaria, el segundo choca con un 409 y se retira solo.
--
-- Tampoco puede vivir en memoria como los flags de WOL: Fly escala a cero, y un cold
-- start a media mañana borraría la marca y mandaría el correo por segunda vez.

create table if not exists public.brief_envios (
    fecha        date         primary key,
    enviado_at   timestamptz  not null default now(),
    -- Qué lo disparó: 'despertar' (señal del móvil), 'sueno' (llegó el dato del
    -- Watch), 'tope' (nadie dio señal y venció BRIEF_HORA_TOPE) o 'manual'.
    fuente       text         not null default 'desconocida',
    -- Hora de la señal de despertar, cuando la hubo. Es lo que permite decidir
    -- después a qué hora toca lanzar la rutina que redacta el briefing.
    despertar_at timestamptz
);

-- Sin policies a propósito: solo entra el backend con la service key, que salta la
-- RLS por diseño. Sin esta línea, la anon key (pública) abriría la tabla al REST de
-- Supabase desde internet.
alter table public.brief_envios enable row level security;
