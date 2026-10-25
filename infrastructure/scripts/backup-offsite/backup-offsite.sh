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
  /mnt/tank/backups             # datastore de PBS: las VM y los CT (OPNsense, docker-main, docker-aux)
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

# Vigilante de temperatura: uno de los SSD de vault va en una bahía con poco aire y llegó
# a 67 °C con la primera copia. Si alguno pasa de TEMP_PAUSE, el proceso se congela
# (SIGSTOP) y sigue (SIGCONT) cuando bajan de TEMP_RESUME. Se puede ajustar en el .env.
read -ra TEMP_DISKS <<<"${TEMP_DISKS:-/dev/sda /dev/sdb}"
TEMP_PAUSE="${TEMP_PAUSE:-58}"
TEMP_RESUME="${TEMP_RESUME:-48}"

max_temp() {
  local d t m=0
  for d in "${TEMP_DISKS[@]}"; do
    t=$(smartctl -A "$d" 2>/dev/null | awk '$1 == 194 {print $10}')
    [ "${t:-0}" -gt "$m" ] && m=$t
  done
  echo "$m"
}

with_temp_guard() {  # with_temp_guard <comando…>
  "$@" &
  local pid=$! paused=0 t
  while kill -0 "$pid" 2>/dev/null; do
    sleep 30
    t=$(max_temp)
    if [ "$paused" = 0 ] && [ "$t" -ge "$TEMP_PAUSE" ]; then
      kill -STOP "$pid" && paused=1
      echo "$(date -Is) pausa: SSD a $t °C"
      notify 3 thermometer "Backup externo en pausa" \
        "Un SSD de vault está a $t °C. La copia sigue cuando baje de $TEMP_RESUME °C."
    elif [ "$paused" = 1 ] && [ "$t" -le "$TEMP_RESUME" ]; then
      kill -CONT "$pid" && paused=0
      echo "$(date -Is) sigue: SSD a $t °C"
    fi
  done
  wait "$pid"
}

# Vigilante de atascos: a veces una petición a Proton se queda colgada sin error y rclone
# espera para siempre (el 2026-10-24 estuvo 2 h quieta en el 69 %; el 2026-10-25, 9 h en
# el 58 % tras un 502). Si en STALL_MIN minutos no avanza, se corta y se relanza; sync sigue
# por donde iba. El avance se pregunta a rclone por su interfaz de control (bytes subidos,
# ficheros comprobados o transferidos y errores): los bytes leídos del proceso no valen,
# porque cuentan también lo que llega por la red y una conexión colgada sigue recibiendo.
STALL_MIN="${STALL_MIN:-15}"
UPLOAD_ATTEMPTS="${UPLOAD_ATTEMPTS:-5}"
RC_ADDR="${RC_ADDR:-127.0.0.1:5572}"

rclone_progress() {  # suma de contadores de rclone; vacío si no responde (al arrancar o al acabar)
  rclone rc --url "http://$RC_ADDR" core/stats 2>/dev/null | python3 -c '
import sys, json
s = json.load(sys.stdin)
print(sum(s.get(k, 0) for k in ("bytes", "checks", "transfers", "errors")))' 2>/dev/null || true
}

with_stall_guard() {  # with_stall_guard <comando de rclone…> (se le añade --rc)
  local try pid last now quiet
  for try in $(seq 1 "$UPLOAD_ATTEMPTS"); do
    "$@" --rc --rc-addr "$RC_ADDR" --rc-no-auth &
    pid=$! last=-1 quiet=0
    while kill -0 "$pid" 2>/dev/null; do
      sleep 60
      now=$(rclone_progress || true)   # con set -e, una consulta fallida no debe tumbar la copia
      if [ -z "$now" ] || [ "$now" != "$last" ]; then quiet=0 last=${now:--1}; else quiet=$((quiet + 1)); fi
      if [ "$quiet" -ge "$STALL_MIN" ]; then
        echo "$(date -Is) atascada $STALL_MIN min: se corta (intento $try de $UPLOAD_ATTEMPTS)"
        kill "$pid" 2>/dev/null || true; sleep 10; kill -9 "$pid" 2>/dev/null || true
        break
      fi
    done
    [ "$quiet" -ge "$STALL_MIN" ] && continue
    wait "$pid"; return
  done
  echo "$(date -Is) la subida se atascó en los $UPLOAD_ATTEMPTS intentos"
  return 1
}

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
# Límite de escritura en el repo local (KiB/s): a ~11 MB/s el SSD caliente se quedó en 52 °C
with_temp_guard nice -n 19 ionice -c3 restic backup --exclude-file "$SCRIPT_DIR/excludes.txt" \
  --limit-upload "${RESTIC_LIMIT_UPLOAD:-10240}" --tag nocturno "${PATHS[@]}"

STEP="restic forget"
if [ "$(date +%u)" = 7 ]; then
  # Poda semanal: es local, pero los paquetes reescritos hay que volver a subirlos
  with_temp_guard restic forget --keep-daily 30 --keep-weekly 12 --keep-monthly 6 --prune \
    --limit-upload "${RESTIC_LIMIT_UPLOAD:-10240}"
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
with_stall_guard nice -n 19 ionice -c3 rclone sync "$RESTIC_REPOSITORY" "$RCLONE_DEST" \
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
