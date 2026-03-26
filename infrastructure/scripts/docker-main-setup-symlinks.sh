# scripts/setup-symlinks.sh
#!/bin/bash
GIT_ROOT="/mnt/nas/git-storage/homelab/services/docker-compose"
APPDATA_ROOT="/opt"

declare -A SERVICES=(
  ["forgejo"]="devops/forgejo"
  ["woodpecker-server"]="devops/woodpecker"
  ["harbor"]="devops/harbor"
  ["portainer"]="devops/portainer"
)

for svc in "${!SERVICES[@]}"; do
  target="${GIT_ROOT}/${SERVICES[$svc]}"
  link="${APPDATA_ROOT}/${svc}/compose"
  mkdir -p "${APPDATA_ROOT}/${svc}"
  ln -sfn "$target" "$link"
  echo "✓ $link → $target"
done