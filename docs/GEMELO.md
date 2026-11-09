<!-- Parte de la guía del repositorio. El índice y las reglas que aplican
     SIEMPRE están en CLAUDE.md, en la raíz. -->

## El gemelo de la casa

Del 2026-11-09, en `gemelo/`. Una automatización nueva se estrena a ciegas: se instala, y a
los tres días se descubre que salta cada vez que un sensor se reconecta, o a las cuatro de
la mañana. El gemelo guarda lo que ha pasado en la casa y deja hacer dos cosas con ello:

- **Probar una regla contra el pasado**: cuántas veces habría saltado, cuándo, y cuántas de
  esas son dudosas (tras una reconexión, de madrugada, repetidas, en falso).
- **Sacar las rutinas**: lo que pasa casi todos los días a la misma hora, lo que alguien
  hace a mano justo después de otra cosa, y lo que se queda encendido más de la cuenta.
  Cada una sale con sus números y con una regla ya escrita, lista para probar.

Corre **en `caja`**, que es quien llega a Home Assistant. No gasta nada: ni un modelo ni
una API de pago; todo es contar.

| Fichero | Qué es |
|---|---|
| `gemelo.py` | La entrada: `archivar`, `estado`, `probar`, `rutinas` |
| `historia.py` | El archivo (SQLite) y la lectura de Home Assistant |
| `reglas.py` | El formato de una regla y el reproductor |
| `rutinas.py` | Horarios, secuencias y olvidos |
| `ejemplos/` | Reglas de muestra, con entidades inventadas |
| `gemelo-archivo.{service,timer}` | El temporizador de usuario que archiva a las 04:20 |
| `tests/backend/test_gemelo.py` | Sus tests (estos sí entran en el CI) |

### Lo que no se relaja

1. **Solo lee.** De Home Assistant se piden `/api/states` y `/api/history`. En `gemelo/` no
   hay ni una llamada a un servicio: no puede encender, abrir ni armar nada. Una rutina es
   una **propuesta**; instalarla en Home Assistant lo decide y lo hace una persona.
2. **En la casa vive más gente.** `historia.se_archiva` deja fuera, lo pida quien lo pida,
   `person.*`, `device_tracker.*`, `media_player.*` y `camera.*`. La única ubicación que
   entra es la del móvil que diga la configuración (`movil`): de quién es un móvil no se
   deduce de un comodín. Y los aparatos de los cuartos de otros se excluyen por nombre en
   `excluir`; excluir vale **hacia atrás** (lo ya archivado se borra en la siguiente pasada).
3. **No sale de `caja`.** El archivo dice cuándo hay alguien en casa y cuándo no. Vive en
   `~/gemelo-casa/` con permisos solo para su usuario, y este repositorio, que es público,
   no lleva ni un nombre de entidad de verdad: los ejemplos y los tests son una casa
   inventada.

### El archivo

Home Assistant guarda unos 30 días y borra (`purge_keep_days`). En vez de tocar eso —más
escrituras en el almacenamiento del Green—, `archivar` copia cada noche lo que falte a
`~/gemelo-casa/historia.sqlite`, y la memoria crece sola. Repetirlo no duplica nada.

- **Qué entra**: luces, interruptores, sensores binarios, persianas, clima, cerraduras,
  ventiladores, la alarma, los `input_boolean` y el sol. Los `sensor` numéricos no (son
  cientos y cambian cada minuto): se añaden uno a uno.
- **La configuración**, `~/gemelo-casa/config.json`, que vive solo en `caja`:
  `{"movil": "device_tracker.…", "incluir": ["sensor.temp_*"], "excluir": ["*cuarto_de_otro*"], "puertas": ["binary_sensor.…"]}`.
- **Con cuidado del Green**: 15 entidades por petición y un día cada vez. Con 40, un día
  cargado tardó más de un minuto y se cortó. Si un día no llega, no se marca como hecho y
  la noche siguiente se vuelve a pedir.

Primera pasada (2026-11-09): 31 días, unos 24.000 cambios de 189 entidades, menos de 2 MB.

### Probar una regla

```bash
python3 gemelo/gemelo.py probar gemelo/ejemplos/garaje-abierto.json
python3 gemelo/gemelo.py probar regla.json --dias 14 --lista
```

Una regla no es el YAML de Home Assistant: es lo justo para reproducirla con exactitud, y
se traduce a YAML cuando ya se sabe que vale.

| Parte | Formas |
|---|---|
| `cuando` | `{"entidad", "pasa_a", "de"?, "durante_min"?}` · `{"entidad", "por_encima"\|"por_debajo", "durante_min"?}` · `{"a_las": "HH:MM"}` |
| `si` (todas) | `{"entidad", "es"\|"no_es"}` · `{"entidad", "por_encima"\|"por_debajo"}` · `{"entre": ["22:00", "07:00"]}` · `{"dias": ["lun", …]}` |
| `espera_min` | No vuelve a saltar hasta pasado ese rato |
| `en_falso_si` | `{"entidad", "pasa_a", "antes_de_min"}`: si eso pasa justo después, el disparo sobraba (la puerta se cerró sola a los dos minutos) |

Lo que devuelve, además de la cuenta: en cuántos días distintos, el máximo en un día, por
hora y por día de la semana, y cuatro marcas de «dudoso»:

- **tras reconexión**: el estado anterior era `unavailable`. Como en Home Assistant, un
  disparador de estado sin `de` salta también cuando el sensor vuelve. Es el falso positivo
  de todos los días, y poner `de` lo quita.
- **en falso**: lo que diga `en_falso_si`.
- **en ráfaga**: menos de cinco minutos después del anterior.
- **de madrugada**: antes de las siete.

Dos detalles del reproductor que importan: las condiciones miran el estado **de ese
momento**, no el de ahora; y el primer dato de una entidad no es un cambio (arrancar el
archivo con la puerta ya abierta no es que se abra).

### Las rutinas

```bash
python3 gemelo/gemelo.py rutinas --probar     # cada propuesta, pasada por el reproductor
python3 gemelo/gemelo.py rutinas --todas      # también lo que ya hace una automatización
```

- **Horarios**: el mismo cambio, en una ventana de 40 minutos, al menos 6 días y el 60 % de
  los laborables (o de los fines de semana, que se cuentan aparte).
- **Secuencias**: tras A, B en menos de cinco minutos, el 70 % de las veces y con A
  ocurrido al menos cinco.
- **Olvidos**: algo encendido o abierto más de 4 horas (20 minutos una puerta o una
  persiana), tres veces o más.

Lo que la primera pasada con la casa de verdad obligó a añadir, y por qué está:

- **Solo cuenta lo que se queda.** Un estado de segundos es un paso (`arming` antes de
  `armed`), y la luz que parpadea un minuto al sonar una alarma no «se enciende a las
  siete».
- **Dos entidades del mismo aparato no son una rutina** (el ventilador de una impresora
  cuando carga filamento): se reconocen por el principio del nombre.
- **Lo que responde en menos de tres segundos ya es una automatización**: no lo hace una
  persona. Se marca `ya_automatizada` y no se propone otra vez.
- **Sin corriente no es encendida.** Una luz a la que le quitan la corriente pasa a
  `unavailable`, no a `off`; contarla encendida hasta el siguiente `off` inventaba olvidos
  de horas.
- **Encendido más de la mitad del tiempo es un ajuste**, no un olvido (el «no molestar» de
  un altavoz, el LED de un enchufe).
- **Los sensores de paso no son rutina de nadie**: más de doce cambios al día y se ignora.

Con un mes y una casa con pocas cosas que se enciendan a mano salen pocas, y es lo
esperable; lo que crece con los meses es el archivo, no el umbral.

### Instalarlo en caja

`~/gemelo-casa/config.json` a mano (el móvil y lo que se excluye) y las dos unidades, como
dice la cabecera de `gemelo-archivo.service`. No están aún en HomeLab.

### Lo que falta

- Que Jarvis lo use hablando («¿cuántas veces habría saltado…?», «¿qué rutinas ves?»): una
  herramienta de solo lectura que llame a `probar` y `rutinas`.
- Traducir una regla aprobada al YAML de Home Assistant.
- Leer las automatizaciones que ya hay y pasarlas por el reproductor una a una.
