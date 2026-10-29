#!/usr/bin/env bash
# El README es el escaparate público del repo: resume el homelab sin datos internos.
# Falla si README.md o README-es.md contienen una IP privada concreta, una ruta del NAS
# o un dominio interno. Las notaciones de red genéricas (10.0.x.0/24) sí se permiten.
#
# Uso: readme-check.sh [fichero...]   sin argumentos revisa README.md y README-es.md
set -euo pipefail

HERE="$(dirname "$(readlink -f "$0")")"
REPO="$(git -C "$HERE" rev-parse --show-toplevel 2>/dev/null || { cd "$HERE/../../.." && pwd; })"
cd "$REPO"

[ "$#" -gt 0 ] || set -- README.md README-es.md

PATTERN='\b(10\.[0-9]{1,3}|192\.168|172\.(1[6-9]|2[0-9]|3[01]))\.[0-9]{1,3}\.[0-9]{1,3}\b|/mnt/|\.(lan|home\.arpa)\b'

if grep -nE "$PATTERN" "$@"; then
  echo "readme-check: el README es público y no puede llevar IPs, rutas del NAS ni dominios internos" >&2
  exit 1
fi
