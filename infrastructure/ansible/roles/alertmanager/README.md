# alertmanager

Despliega Alertmanager en el host del grupo `monitoring` (docker-aux) como el rol
`prometheus`: compose del repo en `/opt/alertmanager` con
`docker compose -p alertmanager`, datos y configuración en `/srv/alertmanager`.

- Envía todo al topic `homelab-alertas` de ntfy por webhook, con la plantilla
  integrada `alertmanager` de ntfy (sin puente intermedio). Un receptor por
  severidad que fija la cabecera `Priority`: `critical` 4, `warning` 3 y el resto 2.
- Agrupa por alerta y host; un `NodeDown` inhibe el resto de alertas de ese host.
- Avisa también de las resoluciones (`send_resolved`).
- Variables: `alertmanager_container_ip` y `alertmanager_ntfy_url` (host_vars).
  Prometheus lo conoce con `prometheus_alertmanagers`.
- Tras desplegar valida con `amtool check-config` y recarga con HUP si cambió.

Uso:

    ansible-playbook playbooks/monitoring.yml --tags alertmanager
