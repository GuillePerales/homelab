#!/usr/bin/env bash
# Estado del homelab en una pasada: red, servicios, discos, backups y recursos.
# Solo lee: no cambia nada en ningún host (guarda en local el histórico SMART para ver tendencias).
# Se lanza desde una máquina con acceso SSH (clave, sin contraseña) a todos los hosts.
# Configuración privada (no versionada): ~/.config/homelab-health.env (ver el .env.example)
# Uso: homelab-health.sh [--ntfy] [--informe]
#   por defecto  una línea por comprobación (OK / AVISO / FALLO)
#   --informe    informe en Markdown por secciones, para la revisión mensual
#   --ntfy       además manda el resumen a ntfy
# Código de salida: 0, 1 (avisos) o 2 (fallos).
set -uo pipefail

ENV_FILE="${ENV_FILE:-$HOME/.config/homelab-health.env}"
# shellcheck source=/dev/null
source "$ENV_FILE"   # ver homelab-health.env.example

BACKUP_MAX_AGE_H="${BACKUP_MAX_AGE_H:-26}"
DISK_WARN_PCT="${DISK_WARN_PCT:-85}"
SSD_LIFE_WARN="${SSD_LIFE_WARN:-30}"
HDD_TEMP_WARN="${HDD_TEMP_WARN:-45}"
SSD_TEMP_WARN="${SSD_TEMP_WARN:-55}"
SCRUB_MAX_AGE_D="${SCRUB_MAX_AGE_D:-35}"
MEM_WARN_PCT="${MEM_WARN_PCT:-90}"
STATE_DIR="${STATE_DIR:-$HOME/.local/state/homelab-health}"

NTFY=0; INFORME=0
for arg in "$@"; do
  case "$arg" in
    --ntfy) NTFY=1 ;; --informe) INFORME=1 ;;
    *) echo "uso: $0 [--ntfy] [--informe]" >&2; exit 64 ;;
  esac
done

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# Cada comprobación escribe líneas «nivel|área|detalle»; al final se juntan en orden
ok()   { printf 'ok|%s|%s\n' "$1" "$2"; }
warn() { printf 'warn|%s|%s\n' "$1" "$2"; }
fail() { printf 'fail|%s|%s\n' "$1" "$2"; }

hosts() {  # hosts <lista…>: sin repetidos y en el mismo orden
  printf '%s\n' "$@" | awk 'NF && !seen[$0]++' | tr '\n' ' '
}

remote() {  # remote <host> <comando>
  timeout 30 ssh -n -o BatchMode=yes -o ConnectTimeout=8 "$1" "$2" 2>/dev/null
}

remote_sh() {  # remote_sh <host> < script  (para hosts con csh, como OPNsense)
  timeout 30 ssh -o BatchMode=yes -o ConnectTimeout=8 "$1" sh -s 2>/dev/null
}

# --- Red ---------------------------------------------------------------------

check_reachable() {
  local h name ip
  for h in $(hosts $PVE_NODES $NAS $DOCKER_HOSTS $OPNSENSE); do
    if remote "$h" true; then ok "Hosts" "$h responde por SSH"; else fail "Hosts" "$h no responde por SSH"; fi
  done
  for h in ${PING_HOSTS:-}; do   # nombre:ip, equipos sin SSH
    name=${h%%:*}; ip=${h#*:}
    if ping -c 2 -W 2 "$ip" >/dev/null 2>&1; then ok "Hosts" "$name responde al ping"
    else warn "Hosts" "$name ($ip) no responde al ping"; fi
  done
}

check_network() {
  local out
  out=$(remote_sh "$OPNSENSE" <<'EOF'
pluginctl -r return_gateways_status | python3 -c '
import json, sys
for name, g in json.load(sys.stdin)["dpinger"].items():
    if g["ipprotocol"] == "inet":
        print("gw", name, g["status"], g["delay"].replace(" ", ""), g["loss"].replace(" ", ""))'
drill example.com @127.0.0.1 2>/dev/null | grep -q "^example.com.*IN[[:space:]]*A" && echo "dns ok" || echo "dns fail"
tailscale status --json 2>/dev/null | python3 -c '
import json, sys
d = json.load(sys.stdin); print("ts", d["BackendState"], d["Self"]["Online"])' || echo "ts ? ?"
EOF
) || { fail "Red" "no se puede leer $OPNSENSE"; return; }
  local kind name status delay loss
  while read -r kind name status delay loss; do
    case "$kind" in
      gw)
        if [ "$delay" = "~" ]; then ok "Gateways" "$name sin monitor (no se mide)"
        elif [ "$status" = down ]; then fail "Gateways" "$name caído"
        elif [ "$status" = none ]; then ok "Gateways" "$name en marcha, $delay, pérdida $loss"
        else warn "Gateways" "$name: $status ($delay, pérdida $loss)"; fi ;;
      dns)
        if [ "$name" = ok ]; then ok "DNS" "Unbound resuelve"; else fail "DNS" "Unbound no resuelve example.com"; fi ;;
      ts)
        if [ "$name" = Running ] && [ "$status" = True ]; then ok "Tailscale" "$OPNSENSE conectado"
        else fail "Tailscale" "$OPNSENSE: estado $name, online $status"; fi ;;
    esac
  done <<<"$out"

  # Las descargas tienen que salir por la VPN: su IP pública no puede ser la del resto
  [ -n "${VPN_CONTAINERS:-}" ] || return
  local host_ip c ip
  host_ip=$(remote "$NAS" "curl -s -m 8 https://ifconfig.me")
  for c in $VPN_CONTAINERS; do
    ip=$(remote "$NAS" "docker exec $c curl -s -m 8 https://ifconfig.me")
    if [ -z "$ip" ]; then warn "VPN" "$c sin salida a internet (¿túnel caído o contenedor parado?)"
    elif [ "$ip" = "$host_ip" ]; then fail "VPN" "$c sale por la IP del ISP, no por la VPN"
    else ok "VPN" "$c sale por la VPN, no por el ISP"; fi
  done
}

# --- Servicios ---------------------------------------------------------------

check_gatus() {
  [ -n "${GATUS_URL:-}" ] || return
  curl -s -m 10 "$GATUS_URL/api/v1/endpoints/statuses" >"$TMP/gatus.json" || { fail "Gatus" "no responde"; return; }
  python3 - "$TMP/gatus.json" <<'EOF'
import json, sys
eps = json.load(open(sys.argv[1]))
down = [e["name"] for e in eps if e.get("results") and not e["results"][-1]["success"]]
print(f"fail|Gatus|caídos: {', '.join(down)}" if down else f"ok|Gatus|{len(eps)} endpoints en verde")
EOF
}

check_containers() {
  local h c out bad unhealthy created died latest
  for h in $DOCKER_HOSTS; do
    out=$(remote "$h" 'docker ps -a --format "{{.Names}}|{{.Status}}|{{.Image}}"') || { fail "Docker" "$h no responde"; continue; }
    # Los que se arrancan a mano cuando hacen falta no cuentan como parados
    for c in ${DOCKER_ON_DEMAND:-}; do out=$(grep -v "^$c|" <<<"$out"); done
    bad=$(grep -vE "\|(Up |Created|Exited \(0\))" <<<"$out" | cut -d'|' -f1 | tr '\n' ' ')
    unhealthy=$(grep -E "unhealthy|Restarting" <<<"$out" | cut -d'|' -f1 | tr '\n' ' ')
    created=$(grep -E "\|Created" <<<"$out" | cut -d'|' -f1 | tr '\n' ' ')
    if [ -n "$bad$unhealthy" ]; then fail "Docker" "$h: parados o con error: $bad$unhealthy"
    elif [ -n "$created" ]; then warn "Docker" "$h: creados pero sin arrancar: $created"
    else ok "Docker" "$h: $(grep -c "|Up " <<<"$out") contenedores en marcha"; fi

    latest=$(awk -F'|' '$3 ~ /:latest$/ || $3 !~ /:/ {print $1}' <<<"$out" | tr '\n' ' ')
    [ -n "$latest" ] && warn "Imágenes" "$h: sin versión fijada: $latest"

    # Caídas con error en las últimas 24 h (un reinicio a mano sale con 0 o 143)
    died=$(remote "$h" 'docker events --since 24h --until 0s --filter event=die --format "{{.Actor.Attributes.name}} {{.Actor.Attributes.exitCode}}"' \
      | awk '$2 != 0 && $2 != 143 && $2 != 137 {n[$1]++} END {for (c in n) printf "%s (%d) ", c, n[c]}')
    if [ -n "$died" ]; then warn "Reinicios" "$h: caídas con error en 24 h: $died"
    else ok "Reinicios" "$h: ninguna caída con error en 24 h"; fi
  done
}

check_alerts() {
  remote "$NAS" "midclt call alert.list" >"$TMP/alerts.json" || { fail "Alertas" "no se puede leer $NAS"; return; }
  python3 - "$TMP/alerts.json" <<'EOF'
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

# --- Discos ------------------------------------------------------------------

check_zfs() {
  local out
  out=$(remote "$NAS" "zpool list -H -o name,cap,health") || { fail "ZFS" "no se puede leer $NAS"; return; }
  while read -r name cap health; do
    if [ "$health" != ONLINE ]; then fail "ZFS" "$name está $health"
    elif [ "${cap%\%}" -ge "$DISK_WARN_PCT" ]; then warn "ZFS" "$name al $cap"
    else ok "ZFS" "$name $health, $cap usado"; fi
  done <<<"$out"
  remote "$NAS" "zpool status -x" | grep -q "all pools are healthy" || fail "ZFS" "zpool status -x no está limpio"

  # Scrub y TRIM por pool
  remote "$NAS" "zpool status -t" >"$TMP/zstatus.txt" || return
  python3 - "$SCRUB_MAX_AGE_D" "$TMP/zstatus.txt" <<'EOF'
import re, sys, time
from datetime import datetime
max_d = int(sys.argv[1]); pool = None; pools = {}
for line in open(sys.argv[2]):
    m = re.match(r"\s*pool: (\S+)", line)
    if m:
        pool = m.group(1); pools[pool] = {"scan": "", "untrimmed": 0, "trimming": 0}
    elif pool and "scan:" in line:
        pools[pool]["scan"] = line.strip()
    elif pool and "(untrimmed)" in line:
        pools[pool]["untrimmed"] += 1
    elif pool and "trimming" in line:
        pools[pool]["trimming"] += 1
for name, p in pools.items():
    m = re.search(r"scrub repaired (\S+) .* with (\d+) errors on (.+)$", p["scan"])
    if "scrub in progress" in p["scan"]:
        print(f"ok|Scrub|{name}: scrub en curso")
    elif not m:
        print(f"warn|Scrub|{name}: sin scrub registrado")
    else:
        when = datetime.strptime(m.group(3).strip(), "%a %b %d %H:%M:%S %Y")
        age = (datetime.now() - when).days
        lvl = "fail" if m.group(2) != "0" else ("warn" if age > max_d else "ok")
        print(f"{lvl}|Scrub|{name}: último {when:%Y-%m-%d} (hace {age} d), {m.group(2)} errores, reparado {m.group(1)}")
    if p["trimming"]:
        print(f"ok|TRIM|{name}: TRIM en curso")
    elif p["untrimmed"]:
        print(f"warn|TRIM|{name}: {p['untrimmed']} vdev sin TRIM")
EOF
  local txg
  txg=$(remote "$NAS" "cat /sys/module/zfs/parameters/zfs_txg_timeout")
  [ -n "$txg" ] && ok "ZFS" "zfs_txg_timeout = $txg s"
}

check_smart() {
  local out
  # Atributos: 5 reasignados, 187 incorregibles, 194 temperatura, 197 pendientes, 198 offline,
  # 231 vida SSD, 233 escrito en NAND (GiB), 241 escrito por el sistema (GiB)
  out=$(remote "$NAS" 'for d in $(lsblk -dno NAME,TYPE | awk "\$2==\"disk\"{print \$1}"); do
      rot=$(lsblk -dno ROTA /dev/$d | tr -d " ")
      health=$(smartctl -H /dev/$d | grep -oE "PASSED|FAILED" || echo "?")
      attrs=$(smartctl -A /dev/$d | awk "\$1~/^(5|187|194|197|198|231|233|241)\$/{printf \"%s=%s \", \$1, \$10}")
      test=$(smartctl -l selftest /dev/$d | grep -m1 "^# 1" | cut -c26-55 | sed "s/ *\$//")
      serial=$(smartctl -i /dev/$d | awk -F": *" "/Serial Number/{print \$2}")
      echo "$d|$rot|$health|$attrs|$test|$serial"
    done') || { fail "SMART" "no se puede leer $NAS"; return; }
  printf '%s\n' "$out" >"$TMP/smart.txt"
  mkdir -p "$STATE_DIR"
  python3 - "$SSD_LIFE_WARN" "$HDD_TEMP_WARN" "$SSD_TEMP_WARN" "$TMP/smart.txt" "$STATE_DIR/smart.tsv" <<'EOF'
import os, sys, time
life_warn, hdd_t, ssd_t = map(int, sys.argv[1:4])
state_file = sys.argv[5]
# Histórico de escrituras de los SSD (serie → hora, 233, 241) para calcular la tendencia
hist = {}
if os.path.exists(state_file):
    for row in open(state_file).read().splitlines():
        serial, ts, nand, host = row.split("\t")
        hist.setdefault(serial, []).append((float(ts), int(nand), int(host)))
now = time.time(); new_rows = []
for line in open(sys.argv[4]).read().splitlines():
    disk, rot, health, attrs, test, serial = line.split("|")
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
    if test and not problems:
        desc += f", último test: {test}"
    if problems:
        print(f"fail|SMART|{desc}: {'; '.join(problems)}")
    elif hot or worn:
        print(f"warn|SMART|{desc}" + (": temperatura alta" if hot else "") + (": poca vida" if worn else ""))
    else:
        print(f"ok|SMART|{desc}")
    # Tendencia de escrituras de los SSD desde la medida más antigua de hace al menos 1 día
    if "233" in a and "241" in a:
        nand, host = int(a["233"]), int(a["241"])
        new_rows.append(f"{serial}\t{now:.0f}\t{nand}\t{host}")
        old = [h for h in hist.get(serial, []) if now - h[0] >= 86400]
        if old:
            ts0, nand0, host0 = old[-1]
            days = (now - ts0) / 86400
            dh, dn = host - host0, nand - nand0
            waf = f", amplificación ×{dn / dh:.1f}" if dh > 0 else ""
            print(f"ok|Escrituras|{disk}: {dh / days:.1f} GiB/día del sistema, {dn / days:.1f} GiB/día en NAND{waf} (últimos {days:.0f} d)")
        else:
            waf = f" (×{nand / host:.1f} en toda su vida)" if host else ""
            print(f"ok|Escrituras|{disk}: {host} GiB escritos, {nand} GiB en NAND{waf}; tendencia desde mañana")
# Guarda una medida al día como mucho por disco
with open(state_file, "a") as f:
    for row in new_rows:
        serial = row.split("\t")[0]
        if not hist.get(serial) or now - hist[serial][-1][0] >= 86400:
            f.write(row + "\n")
EOF
}

# --- Backups -----------------------------------------------------------------

check_backups() {
  local node="${PVE_NODES%% *}" json jobs
  json=$(remote "$node" "pvesh get /nodes/\$(hostname)/storage/$PBS_STORAGE/content --content backup --output-format json") \
    || { fail "PBS" "no se puede leer el storage $PBS_STORAGE desde $node"; return; }
  jobs=$(remote "$node" "pvesh get /cluster/backup --output-format json")
  printf '%s' "$json" >"$TMP/backups.json"; printf '%s' "${jobs:-[]}" >"$TMP/jobs.json"
  python3 - "$BACKUP_MAX_AGE_H" "$TMP/backups.json" "$TMP/jobs.json" <<'EOF'
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
        print(f"fail|PBS|{vmid}: ningún backup en PBS")
        continue
    age = (time.time() - latest[vmid]) / 3600
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(latest[vmid]))
    level = "ok" if age <= max_h else "fail"
    extra = "" if vmid in wanted else " (fuera del job de backup)"
    print(f"{level}|PBS|{vmid}: último {when} (hace {age:.0f} h){extra}")
EOF
}

check_forgejo_dump() {
  [ -n "${FORGEJO_HOST:-}" ] && [ -n "${FORGEJO_DUMP_DIR:-}" ] || return
  local newest age
  newest=$(remote "$FORGEJO_HOST" "ls -t '$FORGEJO_DUMP_DIR' | head -1; stat -c %Y \"$FORGEJO_DUMP_DIR/\$(ls -t '$FORGEJO_DUMP_DIR' | head -1)\"")
  if [ -z "$newest" ]; then fail "Forgejo" "ningún volcado de la BD en $FORGEJO_HOST"; return; fi
  age=$(( ($(date +%s) - $(tail -1 <<<"$newest")) / 3600 ))
  if [ "$age" -le "$BACKUP_MAX_AGE_H" ]; then ok "Forgejo" "último volcado de la BD hace $age h"
  else fail "Forgejo" "último volcado de la BD hace $age h ($(head -1 <<<"$newest"))"; fi
}

check_offsite() {
  [ -n "${OFFSITE_ENV:-}" ] || return
  # Estado del cron, última ejecución en el log y último snapshot del repo restic local
  local out
  out=$(remote "$NAS" "
    midclt call cronjob.query | python3 -c 'import json,sys; print(\"cron\", any(c[\"enabled\"] for c in json.load(sys.stdin) if \"backup-offsite\" in c[\"command\"]))'
    if flock -n /run/backup-offsite.lock true 2>/dev/null; then echo 'running False'; else echo 'running True'; fi
    echo \"last \$(grep '^===' /var/log/backup-offsite.log 2>/dev/null | tail -1)\"
    set -a; . '$OFFSITE_ENV'; set +a
    case \"\$RESTIC_REPOSITORY\" in
      /*) timeout 25 restic snapshots --latest 1 --json --no-lock 2>/dev/null \
            | python3 -c 'import json,sys; s=json.load(sys.stdin); print(\"snap\", s[-1][\"time\"][:19] if s else \"-\")' || echo 'snap ?' ;;
      *) echo 'snap remoto' ;;
    esac")
  [ -n "$out" ] || { fail "Copia externa" "no se puede leer $NAS"; return; }
  local cron running last snap age
  cron=$(awk '$1=="cron"{print $2}' <<<"$out")
  running=$(awk '$1=="running"{print $2}' <<<"$out")
  last=$(sed -n 's/^last //p' <<<"$out")
  snap=$(awk '$1=="snap"{print $2}' <<<"$out")
  [ "$cron" = True ] || warn "Copia externa" "el cron de la copia externa está desactivado"
  if [ "$running" = True ]; then ok "Copia externa" "en curso (${last#=== })"
  elif [[ "$last" == *inicio* ]]; then fail "Copia externa" "la última ejecución no terminó (${last#=== }); ver /var/log/backup-offsite.log"
  elif [ -n "$last" ]; then ok "Copia externa" "última ejecución completa (${last#=== })"
  else warn "Copia externa" "no se ha ejecutado nunca"; fi
  case "$snap" in
    ""|"?") warn "Copia externa" "no se puede leer el repo restic local" ;;
    -) warn "Copia externa" "el repo restic local no tiene snapshots todavía" ;;
    remoto) ;;
    *) age=$(( ($(date +%s) - $(date -d "$snap" +%s)) / 3600 ))
       if [ "$age" -le "$BACKUP_MAX_AGE_H" ]; then ok "Copia externa" "último snapshot restic hace $age h"
       else fail "Copia externa" "último snapshot restic hace $age h"; fi ;;
  esac
}

check_snapshots() {
  remote "$NAS" "midclt call pool.snapshottask.query" >"$TMP/snaptasks.json" || { fail "Snapshots" "no se puede leer $NAS"; return; }
  python3 - "$TMP/snaptasks.json" <<'EOF'
import json, sys, time
for t in json.load(open(sys.argv[1])):
    if not t["enabled"]:
        continue
    s = t["schedule"]; st = t.get("state") or {}
    # Margen según la frecuencia: horaria, diaria o semanal
    limit_h = 2 if s["hour"] == "*" else (8 * 24 if s["dow"] != "*" else 26)
    name = f"{t['dataset']} ({t['lifetime_value']} {t['lifetime_unit'].lower()})"
    if st.get("state") == "ERROR":
        print(f"fail|Snapshots|{name}: error en la última ejecución")
    elif "datetime" not in st:
        print(f"warn|Snapshots|{name}: todavía no se ha ejecutado")
    else:
        age = (time.time() - st["datetime"]["$date"] / 1000) / 3600
        lvl = "ok" if age <= limit_h else "fail"
        print(f"{lvl}|Snapshots|{name}: último hace {age:.0f} h")
EOF
}

# --- Recursos ----------------------------------------------------------------

check_resources() {
  local h out total avail load cpus pct
  for h in $(hosts $PVE_NODES $NAS $DOCKER_HOSTS); do
    out=$(remote "$h" 'free -m | awk "/^Mem:/{print \$2, \$7}"; cut -d" " -f1 /proc/loadavg; nproc') || continue
    read -r total avail <<<"$(sed -n 1p <<<"$out")"
    load=$(sed -n 2p <<<"$out"); cpus=$(sed -n 3p <<<"$out")
    pct=$(( (total - avail) * 100 / total ))
    if [ "$pct" -ge "$MEM_WARN_PCT" ] || awk "BEGIN{exit !($load > $cpus)}"; then
      warn "Recursos" "$h: RAM al $pct % de $((total / 1024)) GB, carga $load con $cpus CPU"
    else ok "Recursos" "$h: RAM al $pct % de $((total / 1024)) GB, carga $load con $cpus CPU"; fi
  done
  for h in $(hosts $PVE_NODES $DOCKER_HOSTS); do
    pct=$(remote "$h" "df --output=pcent / | tail -1 | tr -dc 0-9") || continue
    if [ "$pct" -ge "$DISK_WARN_PCT" ]; then warn "Espacio" "$h: / al $pct %"; else ok "Espacio" "$h: / al $pct %"; fi
  done
  # Storages de Proxmox (PBS incluido), vistos desde el primer nodo
  remote "${PVE_NODES%% *}" "pvesm status 2>/dev/null | awk 'NR>1 && \$3==\"active\" {print \$1, \$7}'" \
    | while read -r name pct; do
        pct=${pct%\%}; pct=${pct%.*}
        if [ "$pct" -ge "$DISK_WARN_PCT" ]; then warn "Espacio" "storage $name al $pct %"; else ok "Espacio" "storage $name al $pct %"; fi
      done
}

# --- Ejecución ---------------------------------------------------------------

# Todas a la vez: cada una tarda lo que tarde su host más lento
CHECKS=(reachable network gatus containers alerts versions zfs smart backups forgejo_dump offsite snapshots resources)
for c in "${CHECKS[@]}"; do "check_$c" >"$TMP/$c.out" 2>/dev/null & done
wait
for c in "${CHECKS[@]}"; do cat "$TMP/$c.out"; done >"$TMP/all.txt"

OKS=$(grep -c '^ok|' "$TMP/all.txt"); WARNS=$(grep -c '^warn|' "$TMP/all.txt"); FAILS=$(grep -c '^fail|' "$TMP/all.txt")
SUMMARY="$OKS OK, $WARNS avisos, $FAILS fallos"
REPORT=$(awk -F'|' '{l = ($1 == "ok" ? "OK    " : ($1 == "warn" ? "AVISO " : "FALLO ")); print l " " $2 ": " $3}' "$TMP/all.txt")

if [ "$INFORME" = 1 ]; then
  python3 - "$TMP/all.txt" "$SUMMARY" <<'EOF'
import sys, time
from collections import OrderedDict
sections = OrderedDict([
    ("Red", ["Hosts", "Gateways", "DNS", "Tailscale", "VPN", "Red"]),
    ("Servicios", ["Gatus", "Docker", "Imágenes", "Reinicios", "Alertas", "Versiones"]),
    ("Discos", ["ZFS", "Scrub", "TRIM", "SMART", "Escrituras"]),
    ("Backups", ["PBS", "Forgejo", "Copia externa", "Snapshots"]),
    ("Recursos", ["Recursos", "Espacio"]),
])
icon = {"ok": "✅", "warn": "⚠️", "fail": "❌"}
rows = [l.split("|", 2) for l in open(sys.argv[1]).read().splitlines() if l.count("|") >= 2]
def section_of(area):
    return next((s for s, areas in sections.items() if area in areas), "Otros")
by = OrderedDict((s, []) for s in list(sections) + ["Otros"])
for r in rows:
    by[section_of(r[1])].append(r)
print(f"# Estado del homelab — {time.strftime('%Y-%m-%d %H:%M')}\n")
print(f"**Resumen:** {sys.argv[2]}\n")
print("| Sección | ✅ | ⚠️ | ❌ |\n|---|---|---|---|")
for s, rs in by.items():
    if rs:
        c = {k: sum(1 for r in rs if r[0] == k) for k in icon}
        print(f"| {s} | {c['ok']} | {c['warn']} | {c['fail']} |")
attention = [r for r in rows if r[0] != "ok"]
if attention:
    print("\n## Requiere atención\n")
    for r in sorted(attention, key=lambda r: r[0] != "fail"):
        print(f"- {icon[r[0]]} **{r[1]}**: {r[2]}")
for s, rs in by.items():
    if not rs:
        continue
    print(f"\n## {s}\n\n| | Comprobación | Detalle |\n|---|---|---|")
    for r in rs:
        print(f"| {icon[r[0]]} | {r[1]} | {r[2].replace('|', '/')} |")
EOF
else
  printf '%s\n\n%s\n' "$REPORT" "$SUMMARY"
fi

if [ -n "${NTFY_URL:-}" ] && [ "$NTFY" = 1 ]; then
  prio=$([ "$FAILS" -gt 0 ] && echo 4 || { [ "$WARNS" -gt 0 ] && echo 3 || echo 2; })
  curl -s -m 10 -H "Priority: $prio" -H "Title: Estado del homelab" \
    -d "$SUMMARY"$'\n'"$(grep -vE '^OK' <<<"$REPORT")" "$NTFY_URL/$NTFY_TOPIC" >/dev/null || true
fi

[ "$FAILS" -gt 0 ] && exit 2
[ "$WARNS" -gt 0 ] && exit 1
exit 0
