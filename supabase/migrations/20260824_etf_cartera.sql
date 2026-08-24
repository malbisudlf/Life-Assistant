-- Cartera manual de ETFs (Revolut). Ni Indexa ni Enable Banking pueden leer la
-- cartera de inversión de Revolut: PSD2 solo cubre cuentas de pago, así que se
-- lleva a mano aquí. `etf_holdings` es qué ETFs se trackean; `etf_aportaciones`
-- es cada aportación real, con las participaciones ya calculadas al darla de
-- alta (precio de cierre real del día, sacado de Yahoo Finance) — no se
-- recalculan después. El valor actual del ETF sí es dinámico: participaciones
-- totales × precio de hoy.

create table if not exists public.etf_holdings (
  ticker         text primary key,   -- el que muestra Revolut, ej. "VWCE"
  nombre         text not null,
  simbolo_yahoo  text not null,      -- símbolo + sufijo de bolsa en Yahoo Finance, ej. "VWCE.DE"
  creado_en      timestamptz not null default now()
);

alter table public.etf_holdings enable row level security;

create table if not exists public.etf_aportaciones (
  id               uuid primary key default gen_random_uuid(),
  ticker           text not null references public.etf_holdings(ticker),
  fecha            date not null,
  importe_eur      numeric(12,2) not null check (importe_eur > 0),
  participaciones  numeric(18,8) not null check (participaciones > 0),
  precio_compra    numeric(12,4) not null,
  creado_en        timestamptz not null default now()
);

alter table public.etf_aportaciones enable row level security;
