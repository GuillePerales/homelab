# opnsense_exporter

Despliega `opnsense-exporter` (`0.0.19`, versión fijada) en docker-aux (grupo `monitoring`) con el
compose del repo en `/opt/opnsense-exporter`. Lee por la API de OPNsense lo que no se ve desde fuera:
tráfico y errores por interfaz y VLAN, estado y latencia de las gateways, estados y paquetes de pf,
WireGuard, DHCP de Kea y servicios.

- **No da CPU ni memoria del firewall:** de eso se encarga el plugin `os-node_exporter` de OPNsense
  (job `node`, host `fw-01`), instalado en el propio firewall.
- **Usuario de solo lectura:** `prometheus-exporter`, con los privilegios de lectura que el exporter
  pide y ninguno de administración. La clave y el secreto se pasan por entorno (`OPNSENSE_API_KEY`,
  `OPNSENSE_API_SECRET`) y quedan en el `.env` del host con `0600`; si no se pasan y ya hay `.env`, se
  conservan. Nunca van al repo.
- **Colectores desactivados** (en el compose): Unbound (necesita Extended Statistics y, si no están, falla
  entero; no se toca DNS por esto), tabla ARP (una serie por cliente), cron, IPsec, OpenVPN, CARP y DHCPv6.
- **`opnsense_up` no es fiable:** con OPNsense recientes queda en 0 aunque todo funcione (issue #119 del
  exporter), así que ni el rol ni las alertas lo usan; el rol comprueba que llegan las métricas de las
  interfaces.
- **Regla de firewall:** el exporter entra por la web de OPNsense (443), cubierta por el alias
  `SRV_MONITOR`, al que se añadió su IP.

Uso:

    OPNSENSE_API_KEY=… OPNSENSE_API_SECRET=… ansible-playbook playbooks/monitoring.yml --tags opnsense_exporter
