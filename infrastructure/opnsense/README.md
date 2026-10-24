# OPNsense

Ficheros que se instalan a mano en el cortafuegos (no forman parte de su configuración exportable).

| Fichero | Destino en OPNsense | Para qué |
|---|---|---|
| `rc.syshook.d/monitor/50-ntfy-protonvpn` | `/usr/local/etc/rc.syshook.d/monitor/` (modo 755) | Avisa a ntfy cuando el gateway de ProtonVPN lleva 5 min caído y cuando se recupera |

Notas:

- OPNsense solo lanza las alarmas de un gateway (y, con ellas, los *hooks* de `monitor`) si el gateway pertenece a un grupo de gateways. `PROTONVPN_GW` está en el grupo `PROTONVPN_ALARMA` solo por eso.
- El PHP de OPNsense tiene `allow_url_fopen` desactivado: el script envía con `curl`.
- Proton descarta a ratos el ping a su gateway y dpinger alterna entre caído y bien cada pocos minutos. Por eso una caída solo se avisa si sigue así 5 minutos después (`$hold`), y la recuperación solo si antes se avisó la caída.
- Prueba: `ifconfig wg1 down`, esperar algo más de 5 min (el aviso de caída llega pasada la espera) y `ifconfig wg1 up`. Deben llegar dos avisos.
