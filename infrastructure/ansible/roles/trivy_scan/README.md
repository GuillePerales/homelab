# trivy_scan

Escaneo semanal con Trivy (`aquasec/trivy`, versión fijada) de las imágenes que corren en los hosts Docker
(los LXC y el NAS), desde docker-aux (grupo `monitoring`). Lo hace el script
[`trivy-scan.py`](../../../scripts/trivy-scan/trivy-scan.py), que el rol copia a `/srv/trivy-scan` y lanza un
timer de systemd los sábados por la mañana.

- **Lista de imágenes desde Prometheus:** cAdvisor corre en cada host Docker y `container_last_seen` lleva la
  imagen y la etiqueta `host`. Así docker-aux no necesita SSH ni el socket de Docker de los otros hosts, ni
  reglas de firewall nuevas. Si un cAdvisor está caído, el informe lo dice. El K3s queda fuera: lo cubre
  Trivy Operator.
- **Escaneo por registro** (`--image-src remote`): cada imagen se baja del registro por su tag, que los
  composes fijan, así que es la que corre. Las construidas en local (sin registro) salen como no escaneadas.
  Trivy guarda el análisis por capa en `/srv/trivy-scan/trivy`: tras la primera pasada solo baja lo nuevo.
- **Solo lo accionable:** HIGH y CRITICAL con arreglo publicado (`--ignore-unfixed`).
- **Salida:** resumen a ntfy (topic de diun), informe Markdown en `/srv/trivy-scan/informes/` (se guardan 8)
  y métricas `trivy_scan_*` en el collector textfile del node_exporter.
- **Un fallo del script** (BD de Trivy, Prometheus sin datos) también avisa a ntfy, con prioridad 4.

Uso:

    ansible-playbook playbooks/monitoring.yml --tags trivy_scan
    # a mano en docker-aux:
    systemctl start trivy-scan.service; journalctl -u trivy-scan -f
