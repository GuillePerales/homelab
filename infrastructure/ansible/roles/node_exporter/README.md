# node_exporter

Instala `node_exporter` como servicio systemd con un usuario sin privilegios,
desde la release oficial de GitHub con versión y checksum fijados. Deja la
versión anterior en disco y apunta `/usr/local/bin/node_exporter` a la actual.

Variables en `defaults/main.yml`: versión y checksum, dirección de escucha
(`0.0.0.0:9100`), collectors extra (`systemd`) y carpeta del collector textfile.

Uso (desde `playbooks/monitoring.yml`):

    ansible-playbook playbooks/monitoring.yml --tags node_exporter --check --diff
    ansible-playbook playbooks/monitoring.yml --tags node_exporter --limit docker-aux

Al terminar comprueba que `/metrics` responde con `node_cpu_seconds_total`.
No abre ni cierra puertos: el 9100 lo limita el firewall.
