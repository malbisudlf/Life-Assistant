<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

# Recados: un asunto llevado hasta cerrarlo

«Jarvis, consígueme cita en el dentista.» «Pregúntale a Erik lo del sábado hasta que
conteste.» Pedido el 10 de noviembre de 2026.

`llamar_a_alguien` (`docs/LLAMADAS_TERCEROS.md`) hace **una** llamada y no insiste: si no
lo cogen, te lo dice y decides tú. Un recado es eso mismo con memoria: Jarvis llama, y si no
lo coge, salta el buzón o le dicen «llama el jueves», lo apunta y vuelve él, varios días,
hasta que lo consigue, le dicen que no o se acaba el plazo.

**Estado: escrito y desplegado, apagado.** Para encenderlo:

1. Aplicar la migración `20261110_jarvis_recados` en Supabase.
2. `RECADOS=1` en `backend.env` (con las llamadas a otros ya encendidas) y desplegar.

## Cómo funciona

```
Mikel: «consígueme cita en el dentista, esta semana por la tarde»
   │
   ▼
Jarvis ── recado_encargar(nombre, asunto, mensaje, objetivo, contexto, dias)
   │  busca la clínica en tus contactos, guarda el recado y llama ya (si es hora)
   ▼
cada intento = llamar_a_alguien(…, recado=id)     ← la llamada de siempre
   │
   ▼  al colgar (`_recado_tras_llamada`)
   ├─ no lo cogió / comunicaba / buzón ──▶ siguiente hueco (dos horas, o mañana a las 10)
   ├─ hablaron ──▶ un modelo sin herramientas mira la transcripción (`_recado_juzgar`):
   │        conseguido ──▶ cerrado: «Conseguido. Le dan cita el jueves a las 17:00.»
   │        dijeron que no ──▶ cerrado: «No insisto más.»
   │        «llame mañana a las once» ──▶ el siguiente intento, mañana a las 11:00
   │        ni una cosa ni otra ──▶ siguiente hueco
   └─ sin llamadas o sin plazo ──▶ cerrado: «Lo dejo aquí tras 4 llamadas.»

el reloj (`_recados_tick`, cada 5 min desde /ha/brief-tick)
   └─ recado vencido ──▶ «¿Vuelvo a llamar ahora?»  [Sí, llama] [Hoy no] [Déjalo]
```

De cada paso te llega un aviso con el asunto delante («🗂 cita dentista») y lo que viene
después. Si el recado lo encargaste por teléfono y hubo conversación, además te llama para
contártelo, como las llamadas sueltas.

Tres herramientas, que solo existen con `RECADOS=1`:

| Herramienta | Qué hace |
|---|---|
| `recado_encargar` | Guarda el recado y hace la primera llamada. No se confirma: lo has pedido tú |
| `recados` | Los abiertos (cuántas llamadas van, qué pasó en la última, cuándo es la siguiente) y los últimos cerrados |
| `recado_dejar` | Lo deja: no se llama más. Por su código o por unas palabras («deja lo del dentista») |

Y una cuarta, `recado_seguir`, que **no se anuncia a ningún modelo** (`interna`): es lo que
ejecuta el botón «Sí, llama».

## Las reglas

1. **Cada intento es una llamada a terceros, con todas sus reglas.** Solo a un contacto
   guardado y por su nombre (nunca un número), un modelo sin herramientas al otro lado, y
   presentándose como el asistente de Mikel. En la tabla se guarda el **nombre** del
   contacto, no su teléfono: se busca otra vez en cada llamada.
2. **Insistir se pregunta.** La primera llamada la pediste tú. Antes de cada una de las
   siguientes llega «¿Vuelvo a llamar ahora?» con tres botones: *Sí, llama* (llama en el
   momento), *Hoy no* (mañana a primera hora vuelve a preguntar) y *Déjalo*. No contestar
   **no es un no**: se vuelve a preguntar en el siguiente hueco. Sin móvil que recoja
   avisos no se pregunta ni se llama: por correo no hay botón.
   Con `RECADOS_INSISTE=solo`, o diciéndole «insiste sin preguntarme» (`sin_preguntar`),
   llama él dentro de los topes y solo avisa.
3. **Si dicen que no, se acaba.** «No damos cita por teléfono», «no me llaméis más» o un no
   a secas cierran el recado, también en modo `solo`. Insistir a quien ha dicho que no es
   acosar, y esto llama desde el fijo de casa.
4. **Topes.** `RECADOS_INTENTOS` (4) llamadas por recado, plazo de `dias` (3 por defecto,
   `RECADOS_DIAS_MAX` 7 como mucho), `RECADOS_MAX` (5) abiertos a la vez, y una cosa hacia
   fuera por pasada del reloj.
5. **Su propio horario**, más corto que el de llamar: de `RECADOS_DESDE` (10) a
   `RECADOS_HASTA` (20), y solo de lunes a viernes salvo `tambien_finde` (un amigo sí, una
   clínica no). El botón «Sí, llama» usa el horario general de llamadas: si lo pulsas a las
   21:00, es que quieres que llame.
6. **Lo que dijo la otra persona es un dato.** Decide si se consiguió un modelo sin
   herramientas con campos cerrados, y el código comprueba la fecha de «vuelve a llamar»
   (futura y dentro del plazo; si no, se ignora). Lo ya pasado entra en la llamada
   siguiente como **notas** («ya llamaste el martes y te dijeron…»), en un modelo que no
   puede hacer nada con ellas salvo decirlas. A quién se llama y para qué no cambian nunca
   por lo que diga nadie al teléfono. `recados` devuelve lo dicho con `_AVISO_WEB`, como
   `llamadas_a_otros`.
7. **Solo llama.** No manda correos ni WhatsApp en tu nombre para insistir: eso sigue
   teniendo su botón.

## Lo que hay que saber

- **Sobrevive a un despliegue**, que es para lo que está en una tabla. Una llamada que
  estaba en marcha cuando el backend se reinició se da por fallida a los 20 minutos y se
  reprograma (cuenta como intento).
- **El plazo manda sobre las llamadas**: si el siguiente hueco cae fuera del plazo, se
  cierra aunque queden intentos.
- **Si falta la migración**, encargar un recado lo dice («¿falta la migración…?») y el
  reloj avisa una sola vez en el registro, no cada cinco minutos.
- **Gasta** lo que una llamada a terceros por intento, más una consulta pequeña al modelo
  para juzgarla (`TERCEROS_MODELO`, apuntada en el gasto como `terceros`).

## Lo que no hace

- **No llama a quien no esté en tus contactos.** Para una clínica nueva, guárdala antes.
- **No espera en una centralita** («pulse 1 para citas»): no marca tonos. Con un menú así,
  la llamada acaba sin hablar con nadie y cuenta como intento.
- **No lleva varios asuntos en una llamada** ni llama a dos personas por el mismo recado.
- **No se ha probado todavía con una llamada de verdad**: lo probado son sus 36 tests.
