-- Campo extra para metadatos de proveedor en oauth_tokens.
-- Lo usa la vía BMW (envío de destino al coche) para guardar el gcid de MyBMW
-- junto al refresh token; Graph no lo necesita y lo deja a null.
alter table public.oauth_tokens add column if not exists extra jsonb;
