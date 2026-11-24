# smartctl_exporter

Instala `smartctl_exporter` como servicio systemd en los nodos Proxmox, con un
usuario sin privilegios (grupo `disk` y capacidades ambientales, como el agente
de Beszel). Versión y checksum fijados; deja la versión anterior en disco.

- **Capacidades**: `CAP_SYS_RAWIO` y `CAP_SYS_ADMIN` para las consultas SMART.
- **NVMe**: su `/dev/nvmeN` es `root:root 0600`. Una regla de udev
  (`60-smartctl-exporter-nvme.rules`) lo pone en el grupo `disk` con `0660`, como los discos SATA,
  en vez de darle `CAP_DAC_READ_SEARCH` (leer cualquier fichero del host). Al final el rol
  comprueba que el NVMe sale en las métricas: sin acceso, el exporter arranca y no lo lista.
- **Solo lectura**: lee el SMART cada 5 minutos y no lanza tests.
- `--smartctl.powermode-check=standby`: no despierta un disco dormido.
- Escucha en el 9633 de todas las interfaces; el firewall decide quién llega.
- En nas-01 (TrueNAS, appliance) no se usa este rol: va como contenedor, ver
  `services/docker-compose/monitoring/smartctl-exporter/`.

Uso (desde `playbooks/monitoring.yml`):

    ansible-playbook playbooks/monitoring.yml --tags smartctl_exporter --limit pve-aux
