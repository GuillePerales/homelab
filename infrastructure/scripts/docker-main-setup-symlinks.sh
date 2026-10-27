#!/bin/bash
# infrastructure/scripts/docker-main-setup-symlinks.sh
# Crea en docker-main el enlace /opt/appdata/<svc>/compose/docker-compose.yml al
# compose del repo (clon del NAS montado por NFS). El .env real va junto al enlace
# y los datos en /opt/appdata/<svc>/data (o config/). Despliegue:
#   cd /opt/appdata/<svc>/compose && docker compose -p <svc> up -d
# Gatus y Forgejo tienen aún un docker-compose.yml propio; Portainer vive en /opt/portainer.
GIT_ROOT="/mnt/nas/git-storage/homelab/services/docker-compose"
APPDATA_ROOT="/opt/appdata"

declare -A SERVICES=(
  ["diun"]="monitoring/diun"
  ["homarr"]="monitoring/homarr"
  ["ntfy"]="monitoring/ntfy"
  ["seerr"]="media/seerr"
  ["woodpecker"]="devops/woodpecker"
)

for svc in "${!SERVICES[@]}"; do
  target="${GIT_ROOT}/${SERVICES[$svc]}/docker-compose.yml"
  link="${APPDATA_ROOT}/${svc}/compose/docker-compose.yml"
  mkdir -p "${APPDATA_ROOT}/${svc}/compose"
  ln -sfn "$target" "$link"
  echo "✓ $link → $target"
done
