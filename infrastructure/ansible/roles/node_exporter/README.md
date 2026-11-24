# node_exporter

Instala `node_exporter` como servicio systemd con un usuario sin privilegios,
desde la release oficial de GitHub con versión y checksum fijados. Deja la
versión anterior en disco y apunta `/usr/local/bin/node_exporter` a la actual.

Variables en `defaults/main.yml`: versión y checksum, dirección de escucha
(`0.0.0.0:9100`), collectors extra (`systemd`) y carpeta del collector textfile.

Uso (desde `playbooks/monitoring.yml`):

    ansible-playbook playbooks/monitoring.yml --tags node_exporter --check --diff
    ansible-playbook playbooks/monitoring.yml --tags node_exporter --limit docker-aux

En los nodos con RAPL (los Proxmox) deja a `node_exporter` leer los contadores de energía de la CPU
(`node_rapl_*`): una regla de `systemd-tmpfiles` pone `energy_uj` en `root:node_exporter 0440`, que
la unidad aplica antes de cada arranque. Ningún otro usuario los lee. En los LXC y las VM no hay
RAPL y el rol no hace nada.

Al terminar comprueba que `/metrics` responde con `node_cpu_seconds_total`.
No abre ni cierra puertos: el 9100 lo limita el firewall.
