# prometheus

Despliega Prometheus en el host del grupo `monitoring` (docker-aux) como el resto
de stacks: copia el compose del repo a `/opt/prometheus` y lo levanta con
`docker compose -p prometheus`. Datos y configuración en `/srv/prometheus`
(disco local del CT, no en el NFS de los SSD del NAS).

- `prometheus.yml` se genera desde el inventario: un job `node` con todos los
  hosts de `proxmox`, `docker_hosts` y `k3s_nodes`. Cada host necesita
  `monitoring_address` en su `host_vars` (IP desde la que Prometheus llega a su
  `:9100`; en docker-aux es la del shim de macvlan, porque un contenedor no
  llega a la IP de su propio host).
- Reglas en `files/alerts-nodos.yml`: NodeDown, HighCPU, HighMemory, DiskAlmostFull
  y DiskFull. Las de SMART, HTTP, certificados y consumo llegan con sus exporters.
- Alertmanager: `prometheus_alertmanagers` (vacío hasta que exista su rol).
- Tras desplegar valida con `promtool check config`, recarga con HUP si cambió la
  configuración o las reglas y lista los objetivos caídos.

Uso:

    ansible-playbook playbooks/monitoring.yml --tags prometheus
