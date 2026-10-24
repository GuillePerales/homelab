#!/usr/bin/env bash
# Copia de la configuración de la infraestructura, desde nas-01: config.xml de OPNsense,
# /etc y la BD del clúster de cada nodo Proxmox y la BD de configuración de TrueNAS.
# Lo que PBS no cubre: PBS copia las VM y los CT, no los hosts.
# Deja un .tar.gz por host y día en $DEST (dentro de vault/secrets: snapshots de 90 días y
# copia externa cifrada con backup-offsite) y avisa a ntfy si algo falla.
# Las claves SSH solo pueden ejecutar el comando de copia (command= en authorized_keys).
# La lanza cada noche un cron de TrueNAS, antes de backup-offsite.
# Configuración privada (no versionada): /mnt/vault/secrets/infra-config-backup.env
set -uo pipefail

ENV_FILE="${ENV_FILE:-/mnt/vault/secrets/infra-config-backup.env}"
# shellcheck source=/dev/null
source "$ENV_FILE"   # DEST, KEEP_DAYS, SSH_KEY, OPNSENSE, PVE_NODES, NTFY_URL, NTFY_TOPIC

KEEP_DAYS="${KEEP_DAYS:-30}"
TODAY=$(date +%F)
LOG=/var/log/infra-config-backup.log
FAILED=()

notify() {  # notify <prioridad> <etiquetas> <título> <mensaje>
  curl -s -m 10 -H "Priority: $1" -H "Tags: $2" -H "Title: $3" -d "$4" \
    "$NTFY_URL/$NTFY_TOPIC" >/dev/null || true
}

pull() {  # pull <nombre> <usuario@host>: el comando lo fija authorized_keys en el destino
  local dir="$DEST/$1" out
  mkdir -p "$dir"
  out="$dir/$TODAY.tar.gz"
  if ssh -i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=15 \
      -o UserKnownHostsFile="$(dirname "$SSH_KEY")/known_hosts" "$2" >"$out.tmp" \
      && gzip -t "$out.tmp" 2>/dev/null; then
    mv "$out.tmp" "$out"
    echo "$(date -Is) $1: $(du -h "$out" | cut -f1)"
  else
    rm -f "$out.tmp"
    FAILED+=("$1")
    echo "$(date -Is) $1: FALLO"
  fi
}

truenas() {  # BD de configuración y su semilla (sin ella no se descifran las contraseñas guardadas)
  local dir="$DEST/truenas" tmp
  mkdir -p "$dir"
  tmp=$(mktemp -d)
  if sqlite3 /data/freenas-v1.db ".backup '$tmp/freenas-v1.db'" \
      && cp /data/pwenc_secret "$tmp/" \
      && tar -C "$tmp" -czf "$dir/$TODAY.tar.gz" freenas-v1.db pwenc_secret; then
    echo "$(date -Is) truenas: $(du -h "$dir/$TODAY.tar.gz" | cut -f1)"
  else
    FAILED+=("truenas")
    echo "$(date -Is) truenas: FALLO"
  fi
  rm -rf "$tmp"
}

exec >>"$LOG" 2>&1
echo "=== $(date -Is) inicio"
umask 077

pull opnsense "$OPNSENSE"
for node in $PVE_NODES; do   # «nombre=usuario@host»
  pull "${node%%=*}" "${node#*=}"
done
truenas

find "$DEST" -name '*.tar.gz' -mtime +"$KEEP_DAYS" -delete

if [ "${#FAILED[@]}" -gt 0 ]; then
  notify 4 rotating_light "Copia de configuración fallida" \
    "No se pudo copiar: ${FAILED[*]}. Log: $LOG en nas-01."
  echo "=== $(date -Is) fin con fallos: ${FAILED[*]}"
  exit 1
fi
echo "=== $(date -Is) fin"
