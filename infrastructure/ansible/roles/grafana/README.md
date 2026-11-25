# grafana

Despliega Grafana en el host del grupo `monitoring` (docker-aux) como los roles
`prometheus` y `alertmanager`: compose del repo en `/opt/grafana` con
`docker compose -p grafana`, datos y provisioning en `/srv/grafana`.

- **Provisioning por ficheros**: datasource `Prometheus` (uid `prometheus`, por
  la IP del contenedor en srv-net) y dashboards desde `files/dashboards/*.json`,
  en la carpeta `Homelab`. Los dashboards no se editan en la interfaz
  (`allowUiUpdates: false`): se cambian en el JSON y se relanza el rol.
- **Contraseña de admin**: no vive en el repo. Se pasa por entorno al lanzar el
  playbook (`GRAFANA_ADMIN_PASS`); si no viene y ya hay un `.env` en el host,
  se conserva la existente. Grafana solo la usa al crear la base de datos.
- **Dashboards incluidos**: `Homelab · Visión global` (nodos arriba y caídos,
  alertas activas, CPU, RAM, disco, red, uptime y carga, con selector de nodo).
  `Homelab · Contenedores` (cAdvisor: contenedores, RAM, CPU, red, disco, arranques
  recientes y OOM, con selector de host y de stack). Los de SMART, HTTP y consumo
  llegan con sus exporters.
- Comprueba al final que Grafana responde, que el datasource conecta con
  Prometheus y que los dashboards están cargados.

Uso:

    GRAFANA_ADMIN_PASS=... ansible-playbook playbooks/monitoring.yml --tags grafana
