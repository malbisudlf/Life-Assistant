-- Interruptor del resumen diario: si sale o no, y hasta cuándo está pausado.
--
-- Una SOLA fila que se sobreescribe, igual que `presence`. Y por lo mismo que aquella,
-- no puede ser un flag en memoria como los del WOL: aquellos son ÓRDENES pendientes
-- (perderlas en un cold start de Fly cuesta volver a pulsar un botón) y esto es ESTADO
-- — un apagado que se evapora en el siguiente cold start volvería a mandar el correo
-- solo, que es exactamente lo que se pidió que no pasara.
--
-- `pausado_hasta` es el ÚLTIMO día sin resumen, inclusive: la pausa se agota sola y el
-- correo vuelve al día siguiente sin que nadie tenga que acordarse de reactivarlo. Es
-- la diferencia entre "me voy una semana" y "no lo quiero más", que son las dos cosas
-- que el interruptor tiene que saber decir.
create table if not exists public.brief_ajustes (
  id            text primary key default 'actual' check (id = 'actual'),
  activo        boolean not null default true,
  pausado_hasta date,                                  -- null = sin pausa
  updated_at    timestamptz not null default now()
);

alter table public.brief_ajustes enable row level security;
