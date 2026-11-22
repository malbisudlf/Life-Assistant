# jacobo de noche

Pedido el 2026-11-21: «que jacobo se apague de 00:30 hasta que me despierte». jacobo (la RX
580 con el oído, la voz, Frigate, las pelis y vida) no hace falta de madrugada, gasta y hace
ruido.

```
jacobo (root, jacobo-noche.timer, cada 15 min de 00:30 a 02:45)
   │  POST /jacobo/noche  (llave JACOBO_NOCHE_TOKEN)
   ▼
backend ── ¿llamada en curso? ¿algo puesto en Jellyfin? → «todavía no»
        ── hora de despertar: la próxima alarma, o cuándo suele levantarse, − 15 min
        ── apunta la ventana (vigilante_estado, plan:jacobo-dormido)
   │  {dormir: true, epoch}
   ▼
jacobo ── rtcwake -m no -u -t <epoch>  (el reloj de la placa, en UTC)
       ── systemctl poweroff  …  la placa lo enciende sola a esa hora
```

## Por qué el reloj y no «cuando me despierte» de verdad

La señal de despertar existe (el atajo del cargador, la alarma confirmada, decírselo a
Jarvis: `_anotar_despierto`), pero no hay forma de encender jacobo con ella: está detrás
del Archer, en otra subred que caja, y un paquete de Wake-on-LAN no cruza un router. Así que
la hora se estima para llegar ANTES que él:

1. la próxima alarma de Jarvis en las próximas 16 h (menos las marcadas para saltar);
2. si no, el cuartil bajo de sus primeras señales de despertar de los últimos 28 días, de
   los días del mismo tipo (laborable o fin de semana), con un mínimo de tres;
3. si no, `JACOBO_DESPIERTA_DEFECTO` (08:00).

Se queda con la más temprana de 1 y 2, le resta `JACOBO_MARGEN_MIN` (15) y nunca antes de las
05:00 ni después de las 11:00. El Wake-on-LAN queda puesto en la tarjeta (`ethtool wol g`)
por si algún día se puede: con el Archer como punto de acceso (misma subred que caja), o un
reenvío del puerto 9 con la MAC fija en el Archer, bastaría con mandar el paquete desde
`_anotar_despierto`.

## Lo que no avisa mientras duerme (y sí avisa si no vuelve)

Mientras dura la ventana —hasta la hora de despertar más `JACOBO_GRACIA_MIN` (30)—:

- el vigilante de servicios del backend no cuenta a jacobo como caído (ni llama ni lo dice al
  descolgar);
- las alertas de Grafana que hablan de jacobo («Prometheus no llega a un medidor… de
  jacobo») se callan en `/programado/roto`;
- el latido de Uptime Kuma (`~/kuma-push-jacobo.sh` en caja, fuera del repositorio porque
  lleva IPs y las llaves de los push) pregunta `GET /jacobo/noche/estado` cuando jacobo no
  contesta y manda «dormido».

Pasada la ventana todo vuelve a contar: **si la placa no lo enciende, el aviso llega** como
el de cualquier caída.

## Lo que se pierde de madrugada

Frigate no graba ni detecta (las reglas de `camaras_cuando` no saltan), las descargas se paran
y la transcripción del teléfono pasa a OpenAI (el parche 25 ya caía ahí si jacobo no
contesta). Si hay una llamada o una peli en marcha a las 00:30, se espera.

## Instalarlo

En jacobo, con sudo (pide la contraseña):

```bash
sudo bash ~/jacobo-noche/instalar.sh
```

Copia el script a `/usr/local/sbin/jacobo-noche`, las unidades a `/etc/systemd/system/` y
activa el temporizador. La configuración (`JACOBO_NOCHE_URL`, `JACOBO_NOCHE_TOKEN`,
`JACOBO_NOCHE_IFACE`) va en `/etc/jacobo-noche.env`, chmod 600: si hay un `jacobo-noche.env`
junto al instalador, lo mueve allí. La misma llave en `backend.env` de caja como
`JACOBO_NOCHE_TOKEN`; sin ella, el backend dice 401 y jacobo no se apaga nunca.

Probar que la placa se enciende sola, sin backend: `sudo jacobo-noche --prueba 4` (se apaga
ya y vuelve en 4 minutos). Si no vuelve, en la BIOS de la Gigabyte: *ErP* desactivado y
*Resume by Alarm* (o *RTC Alarm*) permitido.

Mirar qué hizo: `journalctl -t jacobo-noche`. Apagarlo: `JACOBO_NOCHE=0` en el backend, o
`sudo systemctl disable --now jacobo-noche.timer` en jacobo.
