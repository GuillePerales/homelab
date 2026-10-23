#!/usr/bin/env bash
# Copia externa del homelab, desde nas-01: restic a un repo local en el pool de SSD y
# después rclone sync de ese repo a Proton Drive. Restic directo contra Proton se
# atascaba: tras un 502 el fichero queda a medias en Proton (422) y la copia aborta.
# Así restic nunca falla por la red y la subida se puede reintentar sin romper el repo.
# La lanza cada noche un cron de TrueNAS y avisa a ntfy del resultado.
# Configuración privada (no versionada): /mnt/vault/secrets/backup-offsite.env
set -euo pipefail

ENV_FILE="${ENV_FILE:-/mnt/vault/secrets/backup-offsite.env}"
# shellcheck source=/dev/null
source "$ENV_FILE"   # RESTIC_REPOSITORY (local), RCLONE_DEST, RESTIC_PASSWORD_FILE, NTFY_URL, NTFY_TOPIC, DOCKER_MAIN_SSH, DOCKER_MAIN_KEY

export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE
export RESTIC_CACHE_DIR=/mnt/vault/cache/restic
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
STAGING=/mnt/vault/cache/backup-staging
LOG=/var/log/backup-offsite.log

PATHS=(
  /mnt/tank/media/photos        # Immich: originales y volcados diarios de su BD (backups/)
  /mnt/vault/documents
  /mnt/vault/git-storage
  /mnt/vault/secrets
  /mnt/vault/apps               # configuración y BDs de los servicios de docker-nas
  "$STAGING"                    # /opt/appdata de docker-main, traído por SSH
)

notify() {  # notify <prioridad> <etiquetas> <título> <mensaje>
  curl -s -m 10 -H "Priority: $1" -H "Tags: $2" -H "Title: $3" -d "$4" \
    "$NTFY_URL/$NTFY_TOPIC" >/dev/null || true
}

fail() {
  notify 4 rotating_light "Backup externo fallido" \
    "La copia a Proton Drive ha fallado en el paso «${STEP:-?}». Log: $LOG en nas-01."
}
trap fail ERR

# Una sola ejecución a la vez: la primera subida dura horas
exec 9>/run/backup-offsite.lock
flock -n 9 || { echo "$(date -Is) ya hay una copia en marcha" >>"$LOG"; exit 0; }

exec >>"$LOG" 2>&1
echo "=== $(date -Is) inicio"

STEP="appdata de docker-main"
mkdir -p "$STAGING" "$RESTIC_CACHE_DIR"
# La clave solo puede ejecutar el tar (command= en authorized_keys de docker-main)
ssh -i "$DOCKER_MAIN_KEY" -o BatchMode=yes -o ConnectTimeout=15 \
  -o UserKnownHostsFile="$(dirname "$DOCKER_MAIN_KEY")/known_hosts" "$DOCKER_MAIN_SSH" \
  >"$STAGING/docker-main-appdata.tar.gz.tmp"
mv "$STAGING/docker-main-appdata.tar.gz.tmp" "$STAGING/docker-main-appdata.tar.gz"

STEP="restic backup"
nice -n 19 ionice -c3 restic backup --exclude-file "$SCRIPT_DIR/excludes.txt" \
  --tag nocturno "${PATHS[@]}"

STEP="restic forget"
if [ "$(date +%u)" = 7 ]; then
  # Poda semanal: es local, pero los paquetes reescritos hay que volver a subirlos
  restic forget --keep-daily 30 --keep-weekly 12 --keep-monthly 6 --prune
else
  restic forget --keep-daily 30 --keep-weekly 12 --keep-monthly 6
fi

STEP="restic check"
if [ "$(date +%d)" = 01 ]; then
  restic check --read-data-subset=10%
fi

STEP="subida a Proton Drive"
# Un fichero cada vez y con reintentos: Proton responde con 502 sueltos. Los paquetes de
# restic no cambian una vez escritos, así que cada noche solo sube lo nuevo.
# replace-existing-draft: si una subida anterior dejó el fichero a medias, se reemplaza.
nice -n 19 ionice -c3 rclone sync "$RESTIC_REPOSITORY" "$RCLONE_DEST" \
  --transfers 1 --checkers 2 --retries 10 --retries-sleep 30s --low-level-retries 20 \
  --protondrive-replace-existing-draft --stats 10m --stats-one-line -v

STEP="comprobación de Proton Drive"
if [ "$(date +%d)" = 01 ]; then
  # Mismos ficheros y tamaños en los dos lados (no descarga el contenido)
  rclone check "$RESTIC_REPOSITORY" "$RCLONE_DEST" --size-only --one-way
fi

STEP="resumen"
SUMMARY=$(restic stats latest --mode raw-data 2>/dev/null | awk '/Total Size/ {print $3, $4}')
notify 1 white_check_mark "Backup externo correcto" "Copia local y subida a Proton Drive terminadas. Último snapshot: ${SUMMARY:-?}."
echo "=== $(date -Is) fin"
