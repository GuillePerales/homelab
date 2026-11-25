# pve_exporter

Despliega `prometheus-pve-exporter` (`3.12.0`, versión fijada) en docker-aux (grupo `monitoring`) con el
compose del repo en `/opt/pve-exporter`. Lee por la API de Proxmox el estado del clúster: nodos, VM, CT,
almacenamiento, quórum y versión. Complementa a node_exporter, que ve cada nodo como una máquina pero
no sabe nada de las VM ni del clúster.

- **Un solo nodo para todo el clúster:** Prometheus pregunta a un nodo con `cluster=1` (`prometheus_pve_target`)
  y el exporter devuelve el clúster entero. Si ese nodo cae, esa vista se pierde mientras tanto; la caída
  del nodo la avisa node_exporter.
- **Token de solo lectura:** usuario `prometheus@pve` y token `exporter` con el rol `PVEAuditor` en `/`,
  asignado también al token (con `privsep` activo el token no hereda los permisos del usuario). El valor se
  pasa por entorno (`PVE_EXPORTER_TOKEN`) y queda en el `.env` del host con permisos `0600`; si no se pasa
  y ya hay `.env`, se conserva. Nunca va al repo.
- **Sin el colector de configuración** (`--no-collector.config`): pide un permiso que `PVEAuditor` no da y
  solo aporta una métrica.
- **Fallo conocido:** con pve-manager 9.2.41 o posterior, el colector del clúster hace que Prometheus
  rechace todo el scrape (issue #553 del exporter). Con 9.2.21 no se ha visto; si pasa, añadir
  `--no-collector.cluster` al compose y quitarlo cuando haya una versión con el arreglo.
- **Cardinalidad:** `pve_ha_state` y `pve_lock_state` emiten una serie por estado y por VM o CT; el job de
  Prometheus las descarta porque no se usa HA.
- **Copias:** solo dice qué VM no tienen ninguna tarea de copia; el resultado de las copias es de PBS.

Uso:

    PVE_EXPORTER_TOKEN=… ansible-playbook playbooks/monitoring.yml --tags pve_exporter
