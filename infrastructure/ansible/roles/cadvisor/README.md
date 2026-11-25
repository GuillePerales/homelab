# cadvisor

Despliega cAdvisor en cada host Docker (`docker_hosts`) como contenedor con el
compose del repo en `/opt/cadvisor` y `docker compose -p cadvisor`. Prometheus lo
lee por su IP fija en srv-net (`cadvisor_container_ip` en el `host_vars` del host).

- Solo contenedores Docker (`--docker_only`), con intervalo de 30 s y sin las
  métricas que multiplican las series (`percpu`, `tcp`, `udp`, `process`…).
- Conserva las etiquetas del stack y el servicio de compose, para agrupar por stack.
- Comprueba al final que responde y que ve contenedores por nombre: dentro de un
  LXC, cAdvisor puede arrancar sin ver los cgroups de los contenedores.

Uso:

    ansible-playbook playbooks/monitoring.yml --tags cadvisor
