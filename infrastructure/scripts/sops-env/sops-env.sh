#!/usr/bin/env bash
# Secretos de los servicios cifrados con SOPS + age en el repo, como sops.env
# junto al docker-compose.yml de cada servicio. Solo se cifran los valores: los nombres
# de las variables quedan legibles.
# Se lanza desde la máquina que tiene la clave age (SOPS_AGE_KEY_FILE o
# ~/.config/sops/age/keys.txt). La clave no va a los hosts: el texto en claro solo
# viaja por SSH y nunca toca el disco local.
#
# Uso:
#   sops-env.sh pull  <servicio> <host> <ruta .env>   lee el .env del host y lo cifra en el repo
#   sops-env.sh diff  <servicio> <host> <ruta .env>   variables que difieren entre el repo y el host (sin valores)
#   sops-env.sh push  <servicio> <host> <ruta .env>   escribe en el host el .env descifrado (copia previa .bak-FECHA)
#   sops-env.sh check                                 falla si algún sops.env no está cifrado
# <servicio> es el nombre de su carpeta (sonarr) o la ruta bajo services/docker-compose
# (devops/portainer/docker-main). <host> es un alias de ~/.ssh/config.
set -euo pipefail

HERE="$(dirname "$(readlink -f "$0")")"
# La imagen bash del CI no trae git: si falta, la raíz está tres niveles por encima
REPO="$(git -C "$HERE" rev-parse --show-toplevel 2>/dev/null || { cd "$HERE/../../.." && pwd; })"
BASE="$REPO/services/docker-compose"
NAME=sops.env
cd "$REPO"   # sops busca .sops.yaml desde el directorio actual

die() { echo "sops-env: $*" >&2; exit 1; }

service_dir() {  # service_dir <servicio>
  local dirs
  if [[ "$1" == */* ]]; then
    [ -f "$BASE/$1/docker-compose.yml" ] || die "no hay docker-compose.yml en $1"
    echo "$BASE/$1"; return
  fi
  dirs=$(find "$BASE" -mindepth 2 -maxdepth 2 -type d -name "$1" \
    | while IFS= read -r d; do [ ! -f "$d/docker-compose.yml" ] || echo "$d"; done)
  [ -n "$dirs" ] || die "no existe el servicio $1"
  [ "$(wc -l <<<"$dirs")" -eq 1 ] || die "$1 es ambiguo; usa la ruta: ${dirs//$BASE\//}"
  echo "$dirs"
}

remote_env() {  # remote_env <host> <ruta>
  ssh -o BatchMode=yes "$1" "cat $(printf %q "$2")" || die "no se pudo leer $2 en $1"
}

decrypt() {  # decrypt <fichero>
  sops decrypt --input-type dotenv --output-type dotenv "$1"
}

keys_differing() {  # keys_differing <dotenv A> <dotenv B>: nombres con valor distinto o ausentes
  { diff <(grep -E '^[A-Za-z_][A-Za-z0-9_]*=' "$1" | sort) \
         <(grep -E '^[A-Za-z_][A-Za-z0-9_]*=' "$2" | sort) || true; } \
    | sed -nE 's/^[<>] ([^=]+)=.*/\1/p' | sort -u
}

cmd_pull() {
  local dir; dir=$(service_dir "$1")
  remote_env "$2" "$3" | sops encrypt --filename-override "$dir/$NAME" \
    --input-type dotenv --output-type dotenv /dev/stdin >"$dir/$NAME.tmp"
  mv "$dir/$NAME.tmp" "$dir/$NAME"
  echo "cifrado: ${dir#"$REPO"/}/$NAME ($(grep -c -vE '^(#|sops_|$)' "$dir/$NAME") variables)"
}

cmd_diff() {
  local dir changed; dir=$(service_dir "$1")
  [ -f "$dir/$NAME" ] || die "no hay $NAME en ${dir#"$REPO"/}"
  changed=$(keys_differing <(decrypt "$dir/$NAME") <(remote_env "$2" "$3"))
  if [ -z "$changed" ]; then echo "sin diferencias"; else echo "difieren: $changed" | tr '\n' ' '; echo; fi
}

cmd_push() {
  local dir path; dir=$(service_dir "$1"); path=$(printf %q "$3")
  [ -f "$dir/$NAME" ] || die "no hay $NAME en ${dir#"$REPO"/}"
  # cat > sigue los enlaces: algunos .env de los hosts son enlaces y deben seguir siéndolo
  decrypt "$dir/$NAME" | ssh -o BatchMode=yes "$2" \
    "set -e; [ ! -e $path ] || cp -L $path $path.bak-\$(date +%F-%H%M); umask 077; cat > $path"
  echo "escrito en $2:$3; aplicar con docker compose up -d (o Portainer)"
}

cmd_check() {
  local f fail=0
  while IFS= read -r f; do
    grep -q '^sops_mac=' "$f" || { echo "SIN CIFRAR: ${f#"$REPO"/}"; fail=1; }
  done < <(find "$BASE" -name "$NAME")
  [ "$fail" -eq 0 ] && echo "todos los $NAME están cifrados"
  return "$fail"
}

case "${1:-}" in
  pull|diff|push) [ $# -eq 4 ] || die "uso: $0 $1 <servicio> <host> <ruta .env>"; "cmd_$1" "$2" "$3" "$4" ;;
  check) cmd_check ;;
  *) sed -n '9,16p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
