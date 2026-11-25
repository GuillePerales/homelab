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
- Clúster K3s (`prometheus_k3s_address`, vacío lo desactiva): jobs `k3s` (`/metrics` del API
  server, solo las familias que usan el dashboard y las alertas), `k3s-cadvisor` (contenedores)
  y `kube-state-metrics` (estado de los objetos, por el NodePort de
  `services/k8s/platform/monitoring`). En K3s el API server y el kubelet comparten registro de
  métricas, así que `/metrics` en los dos puertos devuelve lo mismo y solo se recoge uno. Las
  credenciales (token de la cuenta `prometheus-externo` y CA de K3s) entran por entorno
  (`K3S_PROMETHEUS_TOKEN`, `K3S_PROMETHEUS_CA`) y quedan en `config/secrets/` del appdata
  (token con dueño nobody y modo 0400); si no vienen, se conservan las del host. Reglas en
  `files/alerts-k3s.yml`, todas con un guardia que exige que k3s-01 lleve 15 minutos
  encendida (se apaga cada noche).
- Alertmanager: `prometheus_alertmanagers` (vacío hasta que exista su rol).
- Tras desplegar valida con `promtool check config`, recarga con HUP si cambió la
  configuración o las reglas y lista los objetivos caídos.

Uso:

    ansible-playbook playbooks/monitoring.yml --tags prometheus
