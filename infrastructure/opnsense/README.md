# OPNsense

Ficheros que se instalan a mano en el cortafuegos (no forman parte de su configuración exportable).

| Fichero | Destino en OPNsense | Para qué |
|---|---|---|
| `rc.syshook.d/monitor/50-ntfy-protonvpn` | `/usr/local/etc/rc.syshook.d/monitor/` (modo 755) | Avisa a ntfy cuando el gateway de ProtonVPN lleva 5 min caído y cuando se recupera |
| `unbound.opnsense.d/k3s-home-arpa.conf` | `/usr/local/etc/unbound.opnsense.d/` | Comodín de Unbound: todo `*.k3s.home.arpa` resuelve al Traefik de k3s-01 (los Ingress del clúster). Los *host overrides* de la web no admiten comodines |

Notas:

- OPNsense solo lanza las alarmas de un gateway (y, con ellas, los *hooks* de `monitor`) si el gateway pertenece a un grupo de gateways. `PROTONVPN_GW` está en el grupo `PROTONVPN_ALARMA` solo por eso.
- El PHP de OPNsense tiene `allow_url_fopen` desactivado: el script envía con `curl`.
- Proton descarta a ratos el ping a su gateway y dpinger alterna entre caído y bien cada pocos minutos. Por eso una caída solo se avisa si sigue así 5 minutos después (`$hold`), y la recuperación solo si antes se avisó la caída.
- Unbound: OPNsense copia lo de `unbound.opnsense.d/` a `/var/unbound/etc/` y lo incluye al reiniciar (`pluginctl -s unbound restart`). Prueba: `host nombre-inventado.k3s.home.arpa 127.0.0.1` en el firewall debe dar la IP de k3s-01. Si cambia la IP de k3s-01, hay que cambiarla aquí y en el firewall.
- Prueba: `ifconfig wg1 down`, esperar algo más de 5 min (el aviso de caída llega pasada la espera) y `ifconfig wg1 up`. Deben llegar dos avisos.
