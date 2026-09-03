<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

# Avísame: que una sesión de Claude Code te avise al móvil y puedas contestarle hablando

**Estado: diseñado, sin implementar.** Este fichero es el plan. Cuando la fase 1 esté
hecha, esta línea cambia y no antes.

Hoy el proyecto tiene un canal que hace exactamente esto y **solo sabe hablar de una
cosa**: el permiso de despliegue (`docs/AVERIAS.md`). El aviso llega al móvil, el botón
«Hablarlo» abre la pantalla de llamada, descuelgas y Jarvis ya sabe qué se ha roto. Todo
eso está construido, probado y funcionando desde septiembre de 2026.

Lo que falta es que **por ese mismo canal quepa cualquier otra cosa**: que una sesión de
Claude Code que acaba de trabajar en el repositorio te diga «esto me pediste, esto he
hecho, esto ha quedado a medias», y que al descolgar puedas contestarle — y que lo que
digas vuelva y siga el trabajo.

```
Sesión de Claude Code: termina lo que le pediste, o se queda BLOQUEADA
      │  POST /sesion/aviso   (X-Auth-Token: SESION_TOKEN)
      │  { titulo, pedido, hecho, pendiente, enlaces[], bloqueado }
      ▼
Backend: lo guarda en `sesion_avisos` y apunta el aviso
      │  notificación al móvil: «Hablarlo» · «Vale»
      ▼
Pulsas «Hablarlo» → dashboard/?llamada=1 → PantallaLlamada
      │  GET /llamada/pendiente → la apertura + el contexto
      ▼
Descuelgas. Jarvis YA sabe qué pediste y qué se hizo (no va a buscarlo)
      │  hablas: «pues cambia X», «mergéalo», «déjalo»
      ▼
Jarvis guarda tu respuesta y dispara una sesión NUEVA con todo el contexto
```

## Las decisiones, y por qué

Cada una responde a una pregunta que se hizo antes de escribir una línea de código.

1. **Solo avisa si lo pediste, o si me quedé bloqueado.** No «cada vez que termine algo».
   Es la regla del teléfono (`docs/LLAMADAS.md`) aplicada un escalón más abajo: *el día
   que suene por algo que podía esperar, dejarás de mirarlo, y con él se irá el aviso que
   sí importaba*. «He acabado» no es una interrupción justificada por sí sola; **tú
   pidiéndomelo, sí**, porque entonces la interrupción la has elegido tú.

2. **Crítico solo si estoy bloqueado.** El aviso atraviesa el silencio del móvil
   (`critico: true`, ver `_notificar`) únicamente cuando el trabajo *se queda parado hasta
   que contestes* — que es literalmente la definición que usa el permiso de despliegue.
   Un «ya está hecho» llega como cualquier otro aviso y espera a que mires.

3. **Token propio, `SESION_TOKEN`.** Un cliente nuevo, una credencial nueva, revocable
   sin arrastrar a nadie. Y de servicio, nunca un JWT de usuario: la invariante 2 de
   `CLAUDE.md` existe porque ya se olvidó dos veces y el cliente se quedó mudo a los 30
   días sin avisar a nadie.

4. **Lo que escribe la sesión es un DATO, no una instrucción.** El `pedido` y el `hecho`
   los redacta un modelo y acaban dentro del prompt de otro modelo *que tiene
   herramientas*. Van delimitados igual que el enunciado de Alud en
   `build_cowork_instruction`. No es paranoia teórica: es el mismo camino, con la
   diferencia de que aquí el texto lo escribe algo nuestro — hoy.

5. **La vuelta es una sesión NUEVA, no la misma esperando.** Una sesión de Claude Code no
   puede quedarse sondeando horas: cierras el terminal, apagas el PC, contestas mañana
   desde el coche. Tu respuesta dispara una routine con el contexto guardado, exactamente
   como el botón «Arreglarlo» de la revisión nocturna (`ARREGLO_FIRE_URL`). Cuesta una
   sesión nueva por respuesta, y ese es el precio de que el canal funcione con el PC
   apagado.

6. **El contexto caduca.** `SESION_AVISO_TTL_HORAS` (48 por defecto). Una respuesta de
   tres días después no revive un trabajo cuyo repositorio ya no se parece: la sesión
   nueva partiría de una foto falsa. Caducado, Jarvis te lo dice en vez de disparar nada.

7. **`GET /llamada/pendiente` unifica, y solo LEE.** Devuelve lo que haya que anunciar al
   descolgar: primero un despliegue esperando permiso (que es lo bloqueante), y si no, el
   aviso de sesión más reciente. `/despliegue/pendiente` se queda como está — quien ya lo
   usa no se entera. Decidir sigue pasando por su endpoint con su PATCH condicional: la
   pantalla informa y pregunta, **no decide**, igual que hoy.

## Las piezas

| Pieza | Dónde | Qué hace |
|---|---|---|
| `POST /sesion/aviso` | `backend/main.py` | Donde una sesión deja «esto me pediste, esto he hecho». Auth `SESION_TOKEN` |
| `sesion_avisos` | `supabase/migrations/` | El contexto guardado: pedido, hecho, pendiente, enlaces, tu respuesta y el estado |
| `GET /llamada/pendiente` | `backend/main.py` | Qué anunciar al descolgar. Solo lee |
| `_apertura_sesion()` | `backend/main.py` | La primera frase, hermana de `_apertura_despliegue()` — **una sola fuente para todos los transportes** |
| Herramienta `responder_a_la_sesion` | El registro de Jarvis | Guarda lo que has dicho y dispara la sesión nueva. `confirmar: True` |
| `SESION_FIRE_URL` / `SESION_FIRE_TOKEN` | config del backend | La routine que revive el trabajo. Otra rutina, otro token (ver `rutinas_triggers`) |
| `PantallaLlamada` | `src/components/Dashboard.jsx` | Ya existe. Solo cambia de dónde saca lo que anuncia |

## Las fases

1. **El aviso.** Tabla, `POST /sesion/aviso`, el aviso al móvil con sus dos botones.
   Al final de esta fase ya sirve para algo: te avisa y lo lees. Sin hablar todavía.
2. **Descolgar y que lo sepa.** `GET /llamada/pendiente` y `_apertura_sesion()`; la
   pantalla de llamada anuncia el contexto y Jarvis lo tiene en el historial.
3. **La vuelta.** La herramienta de Jarvis, la routine y el disparo con tu respuesta.
4. **Que sea cómodo de usar.** Una skill (`avisame`) para que mis sesiones lo llamen sin
   que haya que acordarse del formato.

Las fases 1 y 2 valen por sí solas. La 3 es la que convierte esto en una conversación.

## Lo que puede salir mal (y hay que probar antes de fiarse)

- **Que el canal se llene de ruido.** Es el único riesgo que mata el proyecto entero, y no
  es técnico. Por eso la decisión 1 es la más importante de este fichero.
- **Que la sesión nueva no tenga lo que hacía falta.** Un `hecho` mal redactado es una
  sesión que empieza a ciegas. El contexto guardado tiene que bastar para retomar sin el
  repositorio delante.
- **Que contestes a un aviso ya caducado**, o a uno que se refiere a una rama que ya no
  está. La caducidad lo cubre a medias; la rama borrada, no.
