---
name: avisame
description: Avisa a Mikel al móvil de que tu sesión ha terminado lo que te pidió, o de que te has quedado bloqueado y no puedes seguir sin él. El aviso llega con un botón para hablarlo, y lo que conteste te vuelve como una sesión nueva. Úsala SOLO si te lo ha pedido o si estás bloqueado, nunca por acabar algo sin más.
---

# Avisar a Mikel de que has terminado (o de que estás atascado)

El backend tiene un canal que llega a su móvil, y con un botón que abre una llamada:
descuelga, tú ya sabes de qué va, y lo que conteste dispara una sesión nueva que sigue el
trabajo. El diseño entero, con sus porqués, está en `docs/AVISAME.md`.

Esta skill es la parte fácil: **cuándo llamar y qué escribir**.

## Cuándo se avisa, y cuándo NO

Solo hay dos motivos válidos:

1. **Te lo ha pedido.** «Avísame cuando acabes», «dime algo cuando esté», «me voy, ya me
   contarás». Entonces la interrupción la ha elegido él.
2. **Te has quedado bloqueado.** El trabajo está PARADO hasta que conteste: falta una
   credencial que no puedes crear, hay que decidir entre dos caminos que no son
   equivalentes, o lo que ibas a hacer es irreversible y no tienes permiso.

**No se avisa por terminar algo sin más.** Es la regla más importante de todo esto y no
es una preferencia de estilo: el día que el móvil suene por algo que podía esperar,
dejará de mirarlo — y con él se irá el aviso que sí importaba. Ante la duda, no avises:
el trabajo queda en el repositorio y él lo ve cuando vuelva.

Tampoco se avisa para pedir permiso de despliegue. Eso ya tiene su propio canal
(`docs/AVERIAS.md`) y **ninguna sesión de Claude despliega nunca**.

## Cómo se avisa

```bash
curl -sS -X POST "$BACKEND_URL/sesion/aviso" \
  -H "X-Auth-Token: $SESION_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "titulo": "...",
    "pedido": "...",
    "hecho": "...",
    "pendiente": "...",
    "enlaces": ["https://github.com/..."],
    "bloqueado": false
  }'
```

Si `SESION_TOKEN` o `BACKEND_URL` no están en el entorno de la sesión, **no lo busques
por el repositorio ni lo inventes**: no hay aviso, y lo dices al terminar.

## Qué escribir en cada campo

Lo que pongas aquí es **todo lo que va a tener** la sesión que retome el trabajo. No
tendrá tu conversación ni tu contexto: tendrá estas cinco líneas. Escríbelas para alguien
que abre el repositorio mañana sin saber nada.

| Campo | Qué va | Cómo se escribe |
|---|---|---|
| `titulo` | Una línea que diga de qué va | **Se dice en voz alta al descolgar.** Como se lo contarías de palabra: «he terminado el refactor de helpers». Sin rutas, sin nombres de función largos, sin markdown |
| `pedido` | Qué te pidió, en sus términos | Una o dos frases |
| `hecho` | Qué has hecho de verdad | Lo que has tocado y si está probado. Si algo no funciona, se dice aquí |
| `pendiente` | Qué ha quedado a medias | Vacío si no queda nada. **No lo rellenes por rellenar** |
| `enlaces` | Dónde mirar | PR, rama, issue. Solo `https://`, cinco como mucho |
| `bloqueado` | `true` solo si estás PARADO | Ver abajo |

## `bloqueado` es lo único que interrumpe

Con `true`, el aviso **suena aunque el móvil esté en silencio** y sale en el momento, sea
la hora que sea. Con `false` espera a que mire, y de noche espera a la mañana siguiente.

Ponlo a `true` **solo si el trabajo no puede continuar sin su respuesta**. No es «esto es
importante» ni «esto es urgente»: es «estoy parado». Si has terminado y solo queda algo
que podrías hacer tú mañana, va a `false`.

Cuando lo pongas a `true`, que el `titulo` diga **qué necesitas**, no que estás atascado:
«no sé si mergear el PR 42 o esperar» sirve; «me he quedado bloqueado» no.

## Después de avisar

Termina la sesión y dilo en tu resumen: que has avisado, y si el aviso salió (la
respuesta trae `"avisado": true`). **No te quedes esperando la respuesta.** No llega por
aquí: cuando conteste, se lanza una sesión nueva con este contexto — puede ser dentro de
diez minutos o mañana, y con tu terminal ya cerrado.

Y si pasan más de 48 horas sin que conteste, el aviso caduca: la sesión nueva no se
lanza, porque partiría de una foto del repositorio que ya no se parece.
