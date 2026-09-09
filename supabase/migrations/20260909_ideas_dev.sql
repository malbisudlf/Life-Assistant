-- La checklist de ideas de la zona de desarrollo (docs/ZONA_DEV.md).
--
-- Tabla propia y no la de `ideas`: aquélla es la bandeja de las notas por voz (texto
-- transcrito, extracción con GPT, sugerencia de evento) y esto es una lista de trabajo
-- del proyecto. Compartir tabla habría obligado a una columna "tipo" que separa dos
-- cosas que no se parecen en nada más que en llamarse ideas.
--
-- La forma la copia `docs/IDEAS.md`, que es como ya se piensan aquí las ideas: el QUÉ,
-- el PORQUÉ —la parte que no se puede reconstruir tres meses después— y POR DÓNDE se
-- empieza. Solo el título es obligatorio: una idea que da pereza escribir no se escribe,
-- y media idea apuntada vale más que una completa que se quedó en la cabeza.
create table if not exists public.ideas_dev (
  id          uuid        primary key default gen_random_uuid(),
  titulo      text        not null,
  porque      text,
  por_donde   text,
  -- 1 = una tarde, 2 = medio, 3 = grande o con partes fuera del código. Los mismos
  -- ●/●●/●●● de docs/IDEAS.md. Nulo mientras no se haya pensado: "no lo sé" y "es
  -- pequeña" son cosas distintas, igual que en el resto del proyecto.
  esfuerzo    smallint    check (esfuerzo between 1 and 3),
  area        text,
  estado      text        not null default 'pendiente'
              check (estado in ('pendiente','en_curso','hecha','descartada')),
  creada      timestamptz not null default now(),
  actualizada timestamptz not null default now()
);

-- La zona dev pide siempre la lista entera ordenada por estado y fecha; con decenas de
-- filas no hace falta más índice que la clave primaria.
alter table public.ideas_dev enable row level security;
