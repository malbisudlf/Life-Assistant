-- Lo que cuesta hablar con Jarvis, medido en vez de estimado.
--
-- Los números que hay en docs/JARVIS.md (3.667 tokens de entrada, 94% cacheado) se
-- midieron UNA VEZ y a mano. Desde entonces han entrado el streaming, las frases de
-- relleno, el modo llamada y el teléfono, cada uno con un patrón de gasto distinto, y
-- la única alarma de coste que existía era la factura.
--
-- Una fila por LLAMADA al modelo, no por turno: un turno con tres vueltas de
-- herramientas y un relevo de modelo son cuatro llamadas de precios distintos, y
-- agregarlas antes de guardarlas perdería justo lo que se quiere mirar. La agregación
-- se hace al leer.
--
-- `boca` es por dónde entró la petición (chat, voz, telefono, atajo, brief, ideas…):
-- el reparto por boca es la pregunta que no se puede responder hoy y la que decide si
-- el modo llamada se está comiendo el presupuesto.
--
-- El COSTE EN EUROS NO SE GUARDA: las tarifas cambian y una cifra en euros escrita hoy
-- sería mentira dentro de seis meses sin que nadie se entere. Se guardan los tokens,
-- que son un hecho, y el precio vive en configuración (MODELO_TARIFAS).
create table if not exists public.jarvis_gasto (
  id                uuid        primary key default gen_random_uuid(),
  creado            timestamptz not null default now(),
  boca              text        not null,
  modelo            text        not null,
  tokens_entrada    integer     not null default 0,
  tokens_cacheados  integer     not null default 0,
  tokens_salida     integer     not null default 0,
  -- Segundos de audio para lo que no se cobra por tokens (Whisper). 0 en el resto.
  segundos_audio    numeric     not null default 0
);

create index if not exists jarvis_gasto_creado on public.jarvis_gasto (creado desc);

-- Como todas las tablas del proyecto: solo entra el backend con la service key.
alter table public.jarvis_gasto enable row level security;
