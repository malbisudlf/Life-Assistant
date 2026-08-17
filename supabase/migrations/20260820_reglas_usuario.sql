-- Reglas que Jarvis propone y tú apruebas.
--
-- Es lo que permite que el sistema crezca sin que haya que escribir una función por cada
-- cosa, y SIN romper la regla de fondo del proyecto —el listón vive en el código, no en
-- el criterio del modelo—. Lo que lo reconcilia es que aquí no se guarda lógica: se
-- guarda qué PLANTILLA (de las que el código ya sabe evaluar) y con qué parámetros.
--
-- El modelo solo puede rellenar los huecos de una plantilla existente. No puede inventar
-- una condición nueva, ni escribir código, ni cambiar cómo se evalúa: eso sigue estando
-- en `_PLANTILLAS_REGLA`, en Python, revisable en un diff. Mismo patrón que
-- `mcp_conectar`: el modelo propone, el botón de confirmar aprueba, y lo aprobado queda
-- escrito como datos.
create table if not exists public.reglas_usuario (
  clave      text        primary key,   -- nombre corto; con él se quita
  plantilla  text        not null,      -- cuál de las que el código sabe evaluar
  parametros jsonb       not null default '{}'::jsonb,
  activa     boolean     not null default true,
  creada     timestamptz not null default now(),
  ultima_vez timestamptz
);

alter table public.reglas_usuario enable row level security;
