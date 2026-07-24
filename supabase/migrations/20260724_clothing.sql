-- Conteo de ropa (widget temporal): lleva la cuenta de la ropa comprada hasta
-- que se salda el gasto. Igual que el resto de tablas, solo accesible desde el
-- backend con la service key: RLS activado sin policies.
create table if not exists public.clothing (
  id         uuid primary key default gen_random_uuid(),
  name       text,                                              -- opcional
  price      numeric not null default 0 check (price >= 0),
  currency   text not null default 'EUR' check (currency in ('EUR', 'THB')),
  photo      text,                                              -- data URL (JPEG base64) redimensionada, opcional
  created_at timestamptz not null default now()
);
create index if not exists clothing_created_at_idx on public.clothing (created_at desc);
alter table public.clothing enable row level security;
