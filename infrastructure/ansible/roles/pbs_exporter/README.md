# pbs_exporter

Despliega `pbs-exporter` de natrontech (`v0.10.0`, versión fijada) en docker-aux (grupo `monitoring`) con el
compose del repo en `/opt/pbs-exporter`. Lee por la API de Proxmox Backup Server el uso de los datastores,
cuántas copias hay de cada VM y CT, cuándo fue la última y si se verificó, y la salud del propio host de PBS.
Complementa a `pve_exporter`, que solo dice qué VM no tienen tarea de copia: el resultado de las copias es de PBS.

- **Token de solo lectura:** usuario `prometheus@pbs` y token `exporter` con el rol `Audit` en `/`, asignado
  también al token (con `privsep` activo el token no hereda los permisos del usuario). El valor se pasa por
  entorno (`PBS_EXPORTER_TOKEN`) y queda en el `.env` del host con permisos `0600`; si no se pasa y ya hay
  `.env`, se conserva. Nunca va al repo.
- **Misma red que PBS:** el exporter está en srv-net y PBS también, así que no hace falta regla de firewall.
  El certificado de PBS es autofirmado, de ahí `PBS_INSECURE=true`.
- **El exporter contesta 200 aunque PBS rechace el token** (issue #196, con PBS 4): lo que dice si lee datos es
  `pbs_up`. Por eso el rol termina comprobando que `/metrics` trae `pbs_up 1`, y la alerta `PbsExporterDown`
  mira también esa métrica.
- **Qué no da:** el estado de la limpieza (GC), del prune ni de la sincronización.
- **Verificación:** `pbs_snapshot_vm_last_verify` vale 1 solo si la última copia está verificada y 0 si todavía
  no (el job corre los sábados), así que no distingue un fallo de una verificación pendiente y no hay alerta.
- **Nombre de las copias:** `vm_name` trae el comentario de la copia («clúster, nombre, nodo, id»), no solo
  el nombre; los paneles lo recortan.
- **Copias en curso:** una copia que aún se está haciendo cuenta como reciente (issue #226).

Uso:

    PBS_EXPORTER_TOKEN=… ansible-playbook playbooks/monitoring.yml --tags pbs_exporter
