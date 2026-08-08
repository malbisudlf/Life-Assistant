-- Servidores MCP que Jarvis da de alta en caliente, una vez el usuario los aprueba.
--
-- Hasta ahora la lista blanca vivía solo en JARVIS_MCP_SERVERS (env), y conectar un
-- servidor era editar un secret de Fly y redesplegar. La regla de fondo no cambia —un
-- servidor entra porque lo aprueba UNA PERSONA, nunca porque lo decida el modelo—, pero
-- el mecanismo pasa a ser el botón de confirmar del dashboard: `mcp_conectar` está
-- marcada como acción a confirmar, así que el modelo solo PROPONE el alta.
--
-- El env sigue existiendo y MANDA en caso de conflicto de nombre: lo que el usuario
-- escribió a mano no lo puede pisar nada que se haya dado de alta por conversación.
create table if not exists public.jarvis_mcp_servidores (
  nombre          text primary key,
  url             text        not null,
  token           text        not null default '',
  confiar         boolean     not null default false,
  lectura_directa boolean     not null default true,
  creado          timestamptz not null default now()
);

-- Como el resto de tablas: solo entra el backend con la service key, que salta la RLS por
-- diseño. Sin esto, la anon key (pública) daría acceso desde internet — y aquí hay tokens
-- de terceros guardados.
alter table public.jarvis_mcp_servidores enable row level security;
