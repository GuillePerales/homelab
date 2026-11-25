# Ansible

Roles y playbooks del homelab. Aquí solo está lo que se puede rehacer desde cero. Los nombres del
inventario son alias de `~/.ssh/config` en la máquina de control (de ahí salen la IP de conexión, el
usuario y la clave). Las IPs de los servicios van en el `host_vars` de cada nodo: son direcciones
privadas y este repo ya publica otras. Los secretos nunca: van por entorno desde ficheros locales.

## Estructura

| Ruta | Qué lleva |
|---|---|
| `inventory/hosts.yml` | Los nodos y sus grupos: `proxmox`, `docker_hosts`, `k3s_nodes`, `nas`, `monitoring` |
| `inventory/host_vars/<nodo>.yml` | Lo propio de cada nodo (IP desde la que Prometheus lo lee, IP de sus contenedores…) |
| `playbooks/monitoring.yml` | El stack de monitorización: un play por rol, con una etiqueta (`tags`) por rol |
| `roles/` | `node_exporter`, `smartctl_exporter`, `cadvisor`, `blackbox`, `qbittorrent_exporter`, `dozzle`, `dozzle_agent`, `pve_exporter`, `opnsense_exporter`, `pbs_exporter`, `prometheus`, `alertmanager`, `grafana` |

Ansible no corre en Windows: se lanza desde Linux o desde WSL. Desde WSL, `run-from-wsl.sh` hace el trabajo pesado: exporta `HEAD` (en Windows el árbol de trabajo está en CRLF), resuelve la IP y el usuario de cada nodo con `ssh -G` sobre el `~/.ssh/config` y copia la clave con permisos válidos. Los secretos entran por el entorno del que llama.

    wsl -d Debian bash -lc 'cd /mnt/c/.../homelab && infrastructure/ansible/run-from-wsl.sh [playbook.yml] --check --diff'

Antes de ejecutar nada, `--check --diff` para ver qué cambiaría.

## Qué recoge cada grupo

| Grupo | Roles que se le aplican | Qué entra en Prometheus |
|---|---|---|
| `proxmox` | `node_exporter`, `smartctl_exporter` | métricas del nodo (`:9100`) y SMART de sus discos (`:9633`) |
| `docker_hosts` | `node_exporter`, `cadvisor` | métricas del host y de sus contenedores |
| `dozzle_agents` | `dozzle_agent` | nada en Prometheus: deja al Dozzle de docker-aux leer los logs de sus contenedores |
| `k3s_nodes` | `node_exporter` | métricas del nodo |
| `nas` | ninguno (es un appliance) | node_exporter (modo host), cAdvisor y SMART, los tres en contenedores desplegados a mano; sus IPs van en `monitoring_address`, `cadvisor_container_ip` y `smartctl_address` |
| `firewall` | ninguno (OPNsense no se gestiona con Ansible) | node_exporter del plugin `os-node_exporter`, instalado en el firewall; su IP va en `monitoring_address` |

`prometheus.yml` se genera desde el inventario: añadir un nodo a su grupo y volver a lanzar
el rol `prometheus` basta para que lo recoja. Los dashboards leen las etiquetas solos.

## Añadir un nodo al monitoring

1. **Acceso.** Un alias SSH con su nombre en `~/.ssh/config` de la máquina de control y la
   clave autorizada en el nodo. El rol `node_exporter` descarga el binario `linux-amd64`:
   en otra arquitectura el rol se detiene.
2. **Inventario.** Añadir el nodo al grupo que le toque en `inventory/hosts.yml`.
3. **Variables.** Crear `inventory/host_vars/<nodo>.yml` con:
   - `monitoring_address`: la IP desde la que docker-aux alcanza el puerto 9100 del nodo.
     Si falta, el rol `prometheus` falla al generar la configuración, que es lo esperado.
   - En un host Docker, además `cadvisor_container_ip`: una IP fija libre dentro del bloque
     de srv-net de ese host (el `srv-net-check` del CI falla si un contenedor no fija IP).
   - Para un contenedor que se vea desde el propio host, que la IP quede cubierta por las
     rutas de su `macvlan_shim`.
4. **Firewall.** Abrir TCP 9100 (y 9633 en un Proxmox) desde el host de monitorización hacia
   el nodo. Si el nodo está en otra VLAN, la regla es del firewall, no de Ansible.
5. **Desplegar**, primero en seco y solo sobre el nodo nuevo:

       ansible-playbook playbooks/monitoring.yml --check --diff --limit <nodo>
       ansible-playbook playbooks/monitoring.yml --tags node_exporter,smartctl_exporter,cadvisor --limit <nodo>

   Cada rol comprueba al final que su servicio responde.
6. **Regenerar Prometheus**, que es lo que añade el nodo a la recogida:

       ansible-playbook playbooks/monitoring.yml --tags prometheus --limit monitoring

7. **Comprobar** en Prometheus (`/targets`) que el nodo está `up` en los jobs que le tocan, y
   que aparece en el dashboard de visión global. Mientras falte la regla del firewall saldrá
   caído y la alerta `NodeDown` saltará a los dos minutos.

Si el nodo se conecta como otro usuario, pasarlo con `-e ansible_user=<usuario>`.

## Quitar un nodo

1. Sacarlo de `hosts.yml` y borrar su `host_vars`.
2. Relanzar el rol `prometheus`, para que deje de recogerlo.
3. En el nodo, parar y borrar lo que se instaló: `systemctl disable --now node_exporter`
   (y `smartctl_exporter` en un Proxmox), o el contenedor de cAdvisor con
   `docker compose -p cadvisor down`.

## Qué no hace Ansible aquí

- Las reglas del firewall y los silencios de Alertmanager se hacen a mano.
- Las alertas no se editan en la interfaz: viven en `roles/prometheus/files/` y los
  dashboards en `roles/grafana/files/dashboards/`. Un cambio hecho en la interfaz de Grafana
  no se guarda.
- Las URL que sondea Blackbox salen del fichero de endpoints de Gatus: un servicio nuevo se
  añade allí y se relanza el rol `blackbox`.
