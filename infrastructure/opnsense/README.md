# OPNsense

Ficheros que se instalan a mano en el cortafuegos (no forman parte de su configuración exportable).

| Fichero | Destino en OPNsense | Para qué |
|---|---|---|
| `rc.syshook.d/monitor/50-ntfy-protonvpn` | `/usr/local/etc/rc.syshook.d/monitor/` (modo 755) | Avisa a ntfy cuando el gateway de ProtonVPN cae o se recupera |

Notas:

- OPNsense solo lanza las alarmas de un gateway (y, con ellas, los *hooks* de `monitor`) si el gateway pertenece a un grupo de gateways. `PROTONVPN_GW` está en el grupo `PROTONVPN_ALARMA` solo por eso.
- El PHP de OPNsense tiene `allow_url_fopen` desactivado: el script envía con `curl`.
- Prueba: `ifconfig wg1 down`, esperar a que el gateway pase a *Offline* (~20 s) y `ifconfig wg1 up`. Deben llegar dos avisos.
