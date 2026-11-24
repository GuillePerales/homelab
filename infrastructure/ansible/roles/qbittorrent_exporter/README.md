# qbittorrent_exporter

Despliega el exporter de qBittorrent de martabal (`v2.0.4`, versión fijada) en docker-aux (grupo
`monitoring`) con el compose del repo en `/opt/qbittorrent-exporter`. Lee de la web de
qBittorrent los torrents, las velocidades, el ratio y el estado de conexión, y Prometheus lo recoge
por su IP en srv-net.

- **Autenticación por clave de API** (qBittorrent 5.2 o posterior), no con la contraseña de admin.
  La clave se crea en la web de qBittorrent (*Opciones → WebUI*) y se pasa por entorno al lanzar el
  playbook, con `QBITTORRENT_API_KEY`. Queda en el `.env` del host con permisos `0600`; si no se
  pasa y ya hay un `.env`, el rol conserva la que tiene. Nunca va al repo.
- **Subida y descarga por tracker:** ningún exporter las da directamente. Con
  `ENABLE_LABEL_WITH_TRACKER` (experimental) las métricas por torrent llevan el tracker y se suman
  en PromQL. La URL de announce puede llevar el passkey, así que el job de Prometheus la reduce a
  dominio antes de guardarla.
- **Series:** unas 17 por torrent con los ajustes por defecto; las opciones de alta cardinalidad
  están apagadas y las métricas `qbittorrent_tracker_*` también (llevan la URL completa).
- Al final comprueba que el exporter obtiene datos de qBittorrent, porque su `/healthz` responde
  aunque la clave sea mala.

Uso (desde `playbooks/monitoring.yml`):

    QBITTORRENT_API_KEY=… ansible-playbook playbooks/monitoring.yml --tags qbittorrent_exporter
