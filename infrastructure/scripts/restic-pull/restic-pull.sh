#!/bin/bash
# Copia el repo restic de vault (nas-01, solo lectura por SFTP) al HDD local de pve-main.
# La copia la tira pve-main con una clave SSH que solo permite leer: el NAS no puede
# borrarla aunque se comprometa. Misma contraseña que el repo de origen.
# Uso: restic-pull.sh [copy|check]. Avisa a ntfy si falla (y del resultado del check).
# Instalado en pve-main como /usr/local/bin/restic-pull.sh; cron en restic-pull.cron.
# Configuración privada (no versionada): /etc/restic-pull.env (ver restic-pull.env.example)
set -uo pipefail
export HOME=/root

ENV_FILE="${ENV_FILE:-/etc/restic-pull.env}"
# shellcheck source=/dev/null
source "$ENV_FILE"   # NAS_HOST, NAS_REPO, SSH_KEY, NTFY_URL

export RESTIC_PASSWORD_FILE=/root/.restic-pass RESTIC_FROM_PASSWORD_FILE=/root/.restic-pass
export RESTIC_REPOSITORY=/mnt/backup-restic/vault
export RESTIC_FROM_REPOSITORY="sftp:root@${NAS_HOST}:${NAS_REPO}"
S="sftp.command=ssh -i ${SSH_KEY} -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=15 root@${NAS_HOST} -s sftp"
modo=${1:-copy}
aviso() { curl -s -m 10 -H "Priority: $1" -H "Tags: $2" -H "Title: $3" -d "$4" "$NTFY_URL" >/dev/null || true; }
exec 9>/run/restic-pull.lock
flock -n 9 || { echo "$(date -Is) ya hay una ejecución"; exit 0; }
echo "$(date -Is) inicio $modo"
if ! mountpoint -q /mnt/backup-restic; then
  aviso high warning "Copia local pve-main" "/mnt/backup-restic no está montado; no se copia"; exit 1
fi
case $modo in
  copy)  nice -n 19 ionice -c3 restic copy --no-lock -o "$S"; rc=$? ;;
  check) nice -n 19 ionice -c3 restic check --read-data-subset=5%; rc=$? ;;
  *) echo "modo desconocido"; exit 2 ;;
esac
echo "$(date -Is) fin $modo rc=$rc"
if [ $rc -ne 0 ]; then aviso high warning "Copia local pve-main falló ($modo)" "restic $modo terminó con código $rc; ver /var/log/restic-pull.log en pve-main"; fi
[ "$modo" = check ] && [ $rc -eq 0 ] && aviso low white_check_mark "Copia local pve-main: check OK" "restic check del 5% sin errores"
exit $rc
