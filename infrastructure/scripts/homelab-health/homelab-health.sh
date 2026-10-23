#!/usr/bin/env bash
# Estado del homelab en una pasada: backups de PBS, ZFS, SMART, alertas, contenedores,
# espacio en disco y versiones. Solo lee: no cambia nada en ningún host.
# Se lanza desde una máquina con acceso SSH (clave, sin contraseña) a todos los hosts.
# Configuración privada (no versionada): ~/.config/homelab-health.env (ver el .env.example)
# Salida: una línea por comprobación (OK / AVISO / FALLO) y código 0, 1 (avisos) o 2 (fallos).
set -uo pipefail
shopt -s lastpipe   # report_lines va al final de una tubería y tiene que actualizar los contadores

ENV_FILE="${ENV_FILE:-$HOME/.config/homelab-health.env}"
# shellcheck source=/dev/null
source "$ENV_FILE"   # PVE_NODES, PBS_STORAGE, NAS, DOCKER_HOSTS, OPNSENSE, GATUS_URL, NTFY_URL, NTFY_TOPIC

BACKUP_MAX_AGE_H="${BACKUP_MAX_AGE_H:-26}"
DISK_WARN_PCT="${DISK_WARN_PCT:-85}"
SSD_LIFE_WARN="${SSD_LIFE_WARN:-30}"
HDD_TEMP_WARN="${HDD_TEMP_WARN:-45}"
SSD_TEMP_WARN="${SSD_TEMP_WARN:-55}"

OKS=0; WARNS=0; FAILS=0; REPORT=""
ok()   { REPORT+="OK     $1: $2"$'\n'; OKS=$((OKS + 1)); }
warn() { REPORT+="AVISO  $1: $2"$'\n'; WARNS=$((WARNS + 1)); }
fail() { REPORT+="FALLO  $1: $2"$'\n'; FAILS=$((FAILS + 1)); }

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

remote() {  # remote <host> <comando>
  ssh -n -o BatchMode=yes -o ConnectTimeout=8 "$1" "$2" 2>/dev/null
}

# Cada comprobación imprime líneas «nivel|área|detalle» que recoge report_lines
report_lines() {
  local level area detail
  while IFS='|' read -r level area detail; do
    case "$level" in
      ok) ok "$area" "$detail" ;; warn) warn "$area" "$detail" ;; fail) fail "$area" "$detail" ;;
    esac
  done
}

check_reachable() {
  local h
  for h in $PVE_NODES $NAS $DOCKER_HOSTS $OPNSENSE; do
    remote "$h" true || fail "SSH" "$h no responde"
  done
}

check_backups() {
  local node="${PVE_NODES%% *}" json jobs
  json=$(remote "$node" "pvesh get /nodes/\$(hostname)/storage/$PBS_STORAGE/content --content backup --output-format json") \
    || { fail "Backups" "no se puede leer el storage $PBS_STORAGE desde $node"; return; }
  jobs=$(remote "$node" "pvesh get /cluster/backup --output-format json")
  printf '%s' "$json" >"$TMP/backups.json"; printf '%s' "${jobs:-[]}" >"$TMP/jobs.json"
  python3 - "$BACKUP_MAX_AGE_H" "$TMP/backups.json" "$TMP/jobs.json" <<'EOF' | report_lines
import json, sys, time
max_h = float(sys.argv[1]); backups = json.load(open(sys.argv[2])); jobs = json.load(open(sys.argv[3]))
latest = {}
for b in backups:
    latest[str(b["vmid"])] = max(latest.get(str(b["vmid"]), 0), b["ctime"])
wanted = set()
for j in jobs:
    if j.get("enabled", 1) and j.get("vmid"):
        wanted.update(j["vmid"].split(","))
for vmid in sorted(wanted | set(latest), key=int):
    if vmid not in latest:
        print(f"fail|Backups|{vmid}: ningún backup en PBS")
        continue
    age = (time.time() - latest[vmid]) / 3600
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(latest[vmid]))
    level = "ok" if age <= max_h else "fail"
    extra = "" if vmid in wanted else " (fuera del job de backup)"
    print(f"{level}|Backups|{vmid}: último {when} (hace {age:.0f} h){extra}")
EOF
}

check_zfs() {
  local out
  out=$(remote "$NAS" "zpool list -H -o name,cap,health") || { fail "ZFS" "no se puede leer $NAS"; return; }
  while read -r name cap health; do
    if [ "$health" != ONLINE ]; then fail "ZFS" "$name está $health"
    elif [ "${cap%\%}" -ge "$DISK_WARN_PCT" ]; then warn "ZFS" "$name al $cap"
    else ok "ZFS" "$name $health, $cap usado"; fi
  done <<<"$out"
  remote "$NAS" "zpool status -x" | grep -q "all pools are healthy" || fail "ZFS" "zpool status -x no está limpio"
}

check_smart() {
  local out
  # Atributos: 5 reasignados, 187 incorregibles, 194 temperatura, 197 pendientes, 198 offline, 231 vida SSD
  out=$(remote "$NAS" 'for d in $(lsblk -dno NAME,TYPE | awk "\$2==\"disk\"{print \$1}"); do
      rot=$(lsblk -dno ROTA /dev/$d | tr -d " ")
      health=$(smartctl -H /dev/$d | grep -oE "PASSED|FAILED" || echo "?")
      attrs=$(smartctl -A /dev/$d | awk "\$1~/^(5|187|194|197|198|231)\$/{printf \"%s=%s \", \$1, \$10}")
      test=$(smartctl -l selftest /dev/$d | grep -m1 "^# 1" | cut -c26-55 | sed "s/ *\$//")
      echo "$d|$rot|$health|$attrs|$test"
    done') || { fail "SMART" "no se puede leer $NAS"; return; }
  printf '%s\n' "$out" >"$TMP/smart.txt"
  python3 - "$SSD_LIFE_WARN" "$HDD_TEMP_WARN" "$SSD_TEMP_WARN" "$TMP/smart.txt" <<'EOF' | report_lines
import sys
life_warn, hdd_t, ssd_t = map(int, sys.argv[1:4])
for line in open(sys.argv[4]).read().splitlines():
    disk, rot, health, attrs, test = line.split("|")
    a = dict(kv.split("=") for kv in attrs.split())
    hdd = rot == "1"
    problems = []
    if health != "PASSED":
        problems.append(f"autoevaluación {health}")
    for k, name in (("5", "reasignados"), ("197", "pendientes"), ("198", "incorregibles offline"), ("187", "incorregibles")):
        if int(a.get(k, "0")) > 0:
            problems.append(f"{a[k]} sectores {name}")
    if test and "without error" not in test and "progress" not in test:
        problems.append(f"último test: {test}")
    temp = int(a.get("194", "0"))
    hot = temp >= (hdd_t if hdd else ssd_t)
    life = int(a["231"]) if "231" in a else None
    worn = life is not None and life < life_warn
    desc = f"{disk} ({'HDD' if hdd else 'SSD'}) {temp} °C" + (f", vida {life} %" if life is not None else "")
    if problems:
        print(f"fail|SMART|{desc}: {'; '.join(problems)}")
    elif hot or worn:
        print(f"warn|SMART|{desc}" + (": temperatura alta" if hot else "") + (": poca vida" if worn else ""))
    else:
        print(f"ok|SMART|{desc}")
EOF
}

check_alerts() {
  local json
  remote "$NAS" "midclt call alert.list" >"$TMP/alerts.json" && python3 - "$TMP/alerts.json" <<'EOF' | report_lines
import json, sys
active = [a for a in json.load(open(sys.argv[1])) if not a["dismissed"]]
levels = {}
for a in active:
    levels[a["level"]] = levels.get(a["level"], 0) + 1
if not active:
    print("ok|Alertas|TrueNAS sin alertas activas")
for a in active[:5]:
    lvl = "fail" if a["level"] in ("CRITICAL", "ERROR", "ALERT", "EMERGENCY") else "warn"
    print(f"{lvl}|Alertas|TrueNAS {a['level']}: {a['formatted'][:120]}")
if len(active) > 5:
    print(f"warn|Alertas|TrueNAS: {len(active) - 5} alertas más ({levels})")
EOF
  [ -n "${GATUS_URL:-}" ] || return
  curl -s -m 10 "$GATUS_URL/api/v1/endpoints/statuses" >"$TMP/gatus.json" || { fail "Gatus" "no responde"; return; }
  python3 - "$TMP/gatus.json" <<'EOF' | report_lines
import json, sys
eps = json.load(open(sys.argv[1]))
down = [e["name"] for e in eps if e.get("results") and not e["results"][-1]["success"]]
print(f"fail|Gatus|caídos: {', '.join(down)}" if down else f"ok|Gatus|{len(eps)} endpoints en verde")
EOF
}

check_containers() {
  local h out bad unhealthy created
  for h in $DOCKER_HOSTS; do
    out=$(remote "$h" 'docker ps -a --format "{{.Names}}|{{.Status}}"') || continue
    bad=$(grep -vE "\|(Up |Created|Exited \(0\))" <<<"$out" | cut -d'|' -f1 | tr '\n' ' ')
    unhealthy=$(grep -E "unhealthy|Restarting" <<<"$out" | cut -d'|' -f1 | tr '\n' ' ')
    created=$(grep -E "\|Created" <<<"$out" | cut -d'|' -f1 | tr '\n' ' ')
    if [ -n "$bad$unhealthy" ]; then fail "Docker" "$h: parados o con error: $bad$unhealthy"
    elif [ -n "$created" ]; then warn "Docker" "$h: creados pero sin arrancar: $created"
    else ok "Docker" "$h: $(grep -c "|Up " <<<"$out") contenedores en marcha"; fi
  done
}

check_disk_space() {
  local h pct
  for h in $PVE_NODES $DOCKER_HOSTS; do
    pct=$(remote "$h" "df --output=pcent / | tail -1 | tr -dc 0-9") || continue
    if [ "$pct" -ge "$DISK_WARN_PCT" ]; then warn "Disco" "$h: / al $pct %"; else ok "Disco" "$h: / al $pct %"; fi
  done
}

check_versions() {
  local h v n
  for h in $PVE_NODES; do
    v=$(remote "$h" "pveversion | cut -d/ -f2") || continue
    n=$(remote "$h" "apt list --upgradable 2>/dev/null | grep -c upgradable")
    if [ "${n:-0}" -gt 0 ]; then warn "Versiones" "$h: Proxmox $v, $n paquetes por actualizar (según la última caché de apt)"
    else ok "Versiones" "$h: Proxmox $v al día"; fi
  done
  v=$(remote "$NAS" "midclt call system.version") && ok "Versiones" "$NAS: $v"
  v=$(remote "$OPNSENSE" "opnsense-version") && ok "Versiones" "$OPNSENSE: $v"
}

check_reachable
check_backups
check_zfs
check_smart
check_alerts
check_containers
check_disk_space
check_versions

SUMMARY="$OKS OK, $WARNS avisos, $FAILS fallos"
printf '%s\n%s\n' "$REPORT" "$SUMMARY"

if [ -n "${NTFY_URL:-}" ] && [ "${1:-}" = "--ntfy" ]; then
  prio=$([ "$FAILS" -gt 0 ] && echo 4 || { [ "$WARNS" -gt 0 ] && echo 3 || echo 2; })
  curl -s -m 10 -H "Priority: $prio" -H "Title: Estado del homelab" \
    -d "$SUMMARY"$'\n'"$(grep -vE '^OK' <<<"$REPORT")" "$NTFY_URL/$NTFY_TOPIC" >/dev/null || true
fi

[ "$FAILS" -gt 0 ] && exit 2
[ "$WARNS" -gt 0 ] && exit 1
exit 0
