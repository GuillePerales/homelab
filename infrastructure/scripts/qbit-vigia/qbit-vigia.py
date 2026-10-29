#!/usr/bin/env python3
"""Vigila qBittorrent y avisa a ntfy de lo que pone en riesgo las cuentas de los trackers privados.

- Riesgo de H&R: un torrent privado completo que no está sembrando (parado, con error o
  sin ficheros) o que ha desaparecido antes de cumplir el seed mínimo de su tracker.
- Torrent rechazado por el tracker (unregistered, passkey inválida, cuenta desactivada…).
- qBittorrent no conectable (sin puerto reenviado) durante dos pasadas seguidas: recrea el
  proyecto de compose (Gluetun + qBittorrent) para que Gluetun coja otro servidor, como mucho
  RECREAR_MAX_DIA veces al día; pasado ese límite solo avisa.
- Resumen semanal: lo sembrado y lo subido por tracker, desde el lado del cliente.

Lo lanza cada 15 min un cron de TrueNAS en nas-01. Habla con qBittorrent por `docker exec`
contra 127.0.0.1, que entra sin contraseña (bypass_local_auth), y solo lee: lo único que
cambia es recrear los contenedores. Cada aviso se manda una vez; el estado vive en STATE_FILE.
Configuración privada (no versionada): /mnt/vault/secrets/qbit-vigia.env
Uso: qbit-vigia.py [--resumen]   (--resumen manda el resumen semanal ya, para probarlo)
"""
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request


def load_env(path):
    env = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"')
    return env


ENV = load_env(os.environ.get("ENV_FILE", "/mnt/vault/secrets/qbit-vigia.env"))
NTFY_URL = ENV["NTFY_URL"]
TOPIC_ALERTAS = ENV.get("NTFY_TOPIC_ALERTAS", "homelab-alertas")
TOPIC_MEDIA = ENV.get("NTFY_TOPIC_MEDIA", "homelab-media")
CONTAINER = ENV.get("QBIT_CONTAINER", "qbittorrent")
STATE_FILE = ENV.get("STATE_FILE", "/mnt/vault/cache/qbit-vigia/state.json")
# horas de seed mínimo por tracker: "torrenteros.org=72,milnueve.cc=96"
SEED_MIN = {k: float(v) for k, v in (p.split("=") for p in ENV.get("SEED_MINIMO", "").split(",") if p)}
SEED_MIN_DEFECTO = float(ENV.get("SEED_MINIMO_DEFECTO", "72"))
RESUMEN_DIA = int(ENV.get("RESUMEN_DIA", "0"))     # 0 = lunes
RESUMEN_HORA = int(ENV.get("RESUMEN_HORA", "9"))
# proyecto de compose de Gluetun + qBittorrent (directorio con su docker-compose.yml y .env)
RECREAR_DIR = ENV.get("RECREAR_DIR", "/mnt/vault/apps/qbittorrent")
RECREAR_PROYECTO = ENV.get("RECREAR_PROYECTO", "qbittorrent")
RECREAR_MAX_DIA = int(ENV.get("RECREAR_MAX_DIA", "3"))

SEMBRANDO = {"uploading", "stalledUP", "forcedUP", "queuedUP", "checkingUP"}
RIESGO = {"stoppedUP", "pausedUP", "error", "missingFiles"}
RECHAZO = re.compile(r"unregistered|not registered|torrent not found|no existe|passkey|banned|"
                     r"account.*disabled|desactivad|baneado|not authorized|unauthorized", re.I)


def qbit(path):
    out = subprocess.run(["docker", "exec", CONTAINER, "wget", "-qO-", f"http://127.0.0.1:8080/api/v2/{path}"],
                         capture_output=True, text=True, timeout=60, check=True).stdout
    return json.loads(out)


def notify(topic, prioridad, etiquetas, titulo, mensaje):
    msg = {"topic": topic, "priority": prioridad, "tags": etiquetas, "title": titulo, "message": mensaje}
    req = urllib.request.Request(NTFY_URL, data=json.dumps(msg).encode(), headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10)


def recrear():
    """Recrea Gluetun y qBittorrent: Gluetun vuelve a pedir servidor y puerto, y qBittorrent
    se engancha a su red nueva (si solo se reinicia Gluetun, qBittorrent se queda sin red)."""
    r = subprocess.run(["docker", "compose", "-p", RECREAR_PROYECTO, "up", "-d", "--force-recreate"],
                       cwd=RECREAR_DIR, capture_output=True, text=True, timeout=600)
    return r.returncode == 0, (r.stderr or r.stdout).strip()[-300:]


def tracker_de(trackers):
    """Dominio del tracker real (http/udp), sin subdominio de tracker."""
    for t in trackers:
        host = urllib.parse.urlparse(t["url"]).hostname
        if host:
            return re.sub(r"^(tracker|announce)\.", "", host)
    return "desconocido"


def seed_min(tracker):
    return next((h for dom, h in SEED_MIN.items() if tracker.endswith(dom)), SEED_MIN_DEFECTO)


def horas(seg):
    return f"{seg / 3600:.0f} h"


def gb(b):
    return f"{b / 1e9:.1f} GB"


def main():
    forzar_resumen = "--resumen" in sys.argv
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    avisados = state.setdefault("avisados", {})       # clave → fecha del aviso
    pendientes = state.setdefault("pendientes", {})   # hash → torrent privado sin cumplir el seed
    primera = "conexion" not in state

    torrents = qbit("torrents/info")
    vivos = {t["hash"] for t in torrents}
    hoy = datetime.date.today().isoformat()

    def avisar_una_vez(clave, *args):
        if clave not in avisados:
            notify(*args)
            avisados[clave] = hoy

    nuevos_pendientes = {}
    tracker_por_hash = {}
    for t in torrents:
        if not t.get("private"):
            continue
        trackers = [x for x in qbit(f"torrents/trackers?hash={t['hash']}") if not x["url"].startswith("**")]
        tracker = tracker_por_hash[t["hash"]] = tracker_de(trackers)
        minimo = seed_min(tracker) * 3600
        completo = t["progress"] >= 1 or t["completion_on"] > 0

        for x in trackers:
            if x["msg"] and RECHAZO.search(x["msg"]):
                avisar_una_vez(f"rechazo:{t['hash']}", TOPIC_ALERTAS, 4, ["no_entry"],
                               f"Tracker rechaza un torrent ({tracker})",
                               f"{t['name']}\nMensaje del tracker: «{x['msg']}». Puede que lo hayan borrado "
                               "del tracker o que haya un problema con la cuenta: revisa la web.")

        if completo and t["seeding_time"] < minimo:
            nuevos_pendientes[t["hash"]] = {"name": t["name"], "tracker": tracker,
                                            "falta": minimo - t["seeding_time"]}
            if t["state"] in RIESGO:
                avisar_una_vez(f"riesgo:{t['hash']}:{t['state']}", TOPIC_ALERTAS, 4, ["warning"],
                               f"Riesgo de H&R en {tracker}",
                               f"{t['name']}\nEstado «{t['state']}» con {horas(t['seeding_time'])} de seed; "
                               f"el mínimo es {horas(minimo)}. Vuelve a ponerlo a sembrar.")

    for h, p in pendientes.items():
        if h not in vivos:
            avisar_una_vez(f"borrado:{h}", TOPIC_ALERTAS, 4, ["rotating_light"],
                           f"Torrent borrado antes del seed ({p['tracker']})",
                           f"{p['name']}\nLe faltaban {horas(p['falta'])} de seed. Si se borró sin querer, "
                           "descarga otra vez el .torrent y vuelve a añadirlo para sembrar.")
    state["pendientes"] = nuevos_pendientes

    # conectable: a la segunda pasada seguida sin puerto (30 min con el cron de 15 min) recrear
    # Gluetun + qBittorrent; si sigue igual, recrear en cada pasada hasta RECREAR_MAX_DIA al día
    info = qbit("transfer/info")
    fallos = state.get("conexion", 0)
    if info["connection_status"] == "connected":
        if fallos >= 2:
            notify(TOPIC_ALERTAS, 2, ["white_check_mark"], "qBittorrent conectable otra vez",
                   "Vuelve a tener el puerto reenviado: los trackers ya pueden conectar contigo.")
        fallos = 0
    else:
        fallos += 1
        if fallos >= 2:
            recreados = state.get("recreados", {})
            hechos = recreados.get("n", 0) if recreados.get("fecha") == hoy else 0
            if hechos < RECREAR_MAX_DIA:
                ok, salida = recrear()
                state["recreados"] = {"fecha": hoy, "n": hechos + 1}
                if ok:
                    notify(TOPIC_ALERTAS, 3, ["arrows_counterclockwise"], "qBittorrent recreado",
                           f"Llevaba más de 15 min en «{info['connection_status']}» (sin puerto reenviado). "
                           f"Recreados Gluetun y qBittorrent para coger otro servidor "
                           f"({hechos + 1}/{RECREAR_MAX_DIA} hoy).")
                else:
                    notify(TOPIC_ALERTAS, 4, ["warning"], "qBittorrent no conectable",
                           f"Falló la recreación automática: {salida}")
            elif hechos == RECREAR_MAX_DIA:
                state["recreados"] = {"fecha": hoy, "n": hechos + 1}
                notify(TOPIC_ALERTAS, 4, ["warning"], "qBittorrent no conectable",
                       f"Sigue en «{info['connection_status']}» tras {RECREAR_MAX_DIA} recreaciones hoy: "
                       "no lo vuelvo a intentar hasta mañana. Mira los logs de gluetun-qbittorrent "
                       "(¿caída de ProtonVPN o de su reenvío de puertos?).")
    state["conexion"] = fallos

    # resumen semanal por tracker (lo que ve el cliente, no la cifra oficial del tracker)
    ahora = datetime.datetime.now()
    toca = ahora.weekday() == RESUMEN_DIA and ahora.hour == RESUMEN_HORA and state.get("resumen") != hoy
    subido_antes = state.get("subido", {})
    if toca or forzar_resumen:
        grupos = {}
        for t in torrents:
            nombre = tracker_por_hash.get(t["hash"], "públicos")
            g = grupos.setdefault(nombre, {"sembrando": 0, "subido": 0, "bajado": 0, "semana": 0})
            g["sembrando"] += t["state"] in SEMBRANDO
            g["subido"] += t["uploaded"]
            g["bajado"] += t["downloaded"]
            g["semana"] += t["uploaded"] - subido_antes.get(t["hash"], 0)
        lineas = []
        for nombre, g in sorted(grupos.items(), key=lambda kv: kv[0] == "públicos"):
            ratio = g["subido"] / g["bajado"] if g["bajado"] else 0
            lineas.append(f"{nombre}: {g['sembrando']} sembrando · {gb(g['semana'])} esta semana · "
                          f"{gb(g['subido'])} subidos en total · ratio {ratio:.2f}")
        s = qbit("sync/maindata")["server_state"]
        lineas.append(f"Total del cliente: {gb(s['alltime_ul'])} subidos · ratio {s['global_ratio']}")
        if primera or not subido_antes:
            lineas.append("(Primer resumen: «esta semana» cuenta todo lo subido hasta hoy.)")
        notify(TOPIC_MEDIA, 2, ["bar_chart"], "Resumen semanal de trackers", "\n".join(lineas))
        state["subido"] = {t["hash"]: t["uploaded"] for t in torrents}
        if toca:
            state["resumen"] = hoy
    elif "subido" not in state:
        state["subido"] = {t["hash"]: t["uploaded"] for t in torrents}

    # olvidar avisos de más de 30 días
    limite = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    state["avisados"] = {k: v for k, v in avisados.items() if v >= limite}

    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE + ".tmp", "w") as f:
        json.dump(state, f)
    os.replace(STATE_FILE + ".tmp", STATE_FILE)


if __name__ == "__main__":
    main()
