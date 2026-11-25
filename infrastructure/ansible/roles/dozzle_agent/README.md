# dozzle_agent

Despliega el agente de Dozzle en los hosts Docker del grupo `dozzle_agents` (hoy docker-main) con el
compose del repo en `/opt/dozzle-agent`. Deja que el hub de docker-aux ([dozzle](../dozzle/README.md))
lea los logs de los contenedores de ese host.

- Escucha en el 7007 de su IP en srv-net (`dozzle_agent_container_ip`, en el `host_vars`) y no
  publica ningún puerto en el host.
- **Ojo con la seguridad:** el certificado TLS del agente es el mismo en todas las copias de la
  imagen, así que cifra pero no identifica a nadie. Cualquiera que llegue al 7007 puede leer los logs
  de ese host. Por eso solo vive en srv-net; si algún día se abre a otra red, hay que darle un
  certificado propio.
- docker-aux no lleva agente: ahí está el hub y lee su propio socket.
- El agente del NAS (TrueNAS es un appliance, sin Ansible) se despliega a mano con el mismo compose,
  como el de smartctl_exporter.
- Al final comprueba que el agente sigue `running` y sin reinicios.

Uso:

    ansible-playbook playbooks/monitoring.yml --tags dozzle_agent --limit docker-main
