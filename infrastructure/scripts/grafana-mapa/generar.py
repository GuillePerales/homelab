#!/usr/bin/env python3
"""Genera el dashboard «Homelab · Mapa» (un panel Canvas de Grafana).

El dibujo sale de INVENTARIO (abajo): hosts, VM/LXC y contenedores con su sitio en el mapa.
El estado de cada caja lo pone Prometheus en vivo (borde verde o rojo). Para añadir un
contenedor, basta una línea en INVENTARIO y volver a ejecutar:

    python3 infrastructure/scripts/grafana-mapa/generar.py

Escribe infrastructure/ansible/roles/grafana/files/dashboards/homelab-mapa.json; se despliega
con el rol grafana (ansible-playbook playbooks/monitoring.yml --tags grafana).

Sin IPs ni puertos: el repo es público. Las consultas usan solo nombres.
"""
import json
import pathlib

SALIDA = (pathlib.Path(__file__).resolve().parents[2]
          / "ansible/roles/grafana/files/dashboards/homelab-mapa.json")

# ── Paleta (la del mapa del README) ─────────────────────────────────────────────
FONDO = "#0d1117"
CAJA = "#161b27"
CAJA_2 = "#1c2333"
LINEA = "#4b5563"
TEXTO = "#e6edf3"
TEXTO_2 = "#8b949e"
NARANJA = "#f0a030"
VLAN = {5: "#3b9eff", 10: "#ff5c5c", 15: "#8b949e", 20: "#ff6bb5",
        30: "#2ed9a0", 40: "#a78bfa", 50: "#f5c518"}

# ── Inventario: contenedores por host Docker (nombre en cAdvisor → etiqueta, sonda HTTP) ──
# La sonda es el `service` de blackbox (probe_success); None si ese servicio no tiene web.
NAS = [
    ("prowlarr", "Prowlarr", "Prowlarr"), ("sonarr", "Sonarr", "Sonarr"),
    ("radarr", "Radarr", "Radarr"), ("lidarr", "Lidarr", "Lidarr"),
    ("bazarr", "Bazarr", "Bazarr"), ("cross-seed", "cross-seed", None),
    ("qbittorrent", "qBittorrent", "qBittorrent"), ("mularr", "Mularr", "Mularr"),
    ("shelfmark", "Shelfmark", "Shelfmark"), ("gluetun-qbittorrent", "Gluetun qBit", None),
    ("gluetun-mularr", "Gluetun Mularr", None), ("syncthing", "Syncthing", "Syncthing"),
    ("jellyfin", "Jellyfin", "Jellyfin"), ("romm", "Romm", "Romm"),
    ("immich-server", "Immich", "Immich"), ("immich-machine-learning", "Immich ML", None),
    ("immich-postgres", "Immich DB", None), ("immich-redis", "Immich Redis", None),
    ("calibre-web-automated", "Calibre-Web", "Calibre-Web"), ("pbs", "PBS", "PBS"),
    ("portainer-agent", "Portainer Ag.", None), ("diun", "diun", None),
    ("dozzle-agent", "Dozzle Ag.", None), ("cadvisor", "cAdvisor", None),
    ("smartctl-exporter", "smartctl", None), ("node-exporter", "node_exporter", None),
    ("beszel-agent", "Beszel Ag.", None),
]
DOCKER_MAIN = [
    ("portainer", "Portainer", "Portainer"), ("forgejo", "Forgejo", "Forgejo"),
    ("woodpecker-server", "Woodpecker", "Woodpecker"), ("woodpecker-agent", "WP agente", None),
    ("homarr", "Homarr", "Homarr"), ("ntfy", "ntfy", "ntfy"),
    ("gatus", "Gatus", None), ("diun", "diun", None),
    ("seerr", "Seerr", "Seerr"), ("agenda", "Agenda", "Agenda"),
    ("beszel", "Beszel", "Beszel"), ("speedtest-tracker", "Speedtest", "Speedtest Tracker"),
    ("salud", "Salud", "Salud"), ("cadvisor", "cAdvisor", None),
    ("dozzle-agent", "Dozzle Ag.", None), ("beszel-agent", "Beszel Ag.", None),
]
DOCKER_AUX = [
    ("portainer-agent", "Portainer Ag.", None), ("prometheus", "Prometheus", None),
    ("alertmanager", "Alertmanager", None), ("grafana", "Grafana", None),
    ("cadvisor", "cAdvisor", None), ("blackbox", "Blackbox", None),
    ("qbittorrent-exporter", "Exp. qBit", None), ("dozzle", "Dozzle", None),
    ("pve-exporter", "Exp. PVE", None), ("opnsense-exporter", "Exp. OPN", None),
    ("pbs-exporter", "Exp. PBS", None), ("beszel-agent", "Beszel Ag.", None),
]

elementos = []


def _color(fijo, campo=None):
    c = {"fixed": fijo}
    if campo:
        c["field"] = campo
    return c


def caja(nombre, x, y, w, h, texto="", fondo=CAJA, borde=LINEA, ancho_borde=1, campo_borde=None,
         tam=12, color=TEXTO, alinea="left", valinea="top", radio=6, texto_campo=None):
    """Rectángulo. `campo_borde` enlaza el color del borde con un campo de Prometheus.

    Canvas no respeta los saltos de línea de un texto fijo: si el texto trae «\\n», la caja se
    dibuja vacía y cada línea es un texto aparte, apilado dentro de ella.
    """
    if texto and "\n" in texto and not texto_campo:
        lineas = texto.split("\n")
        caja(nombre, x, y, w, h, "", fondo, borde, ancho_borde, campo_borde, tam, color, alinea,
             valinea, radio)
        paso = tam + 6
        y0 = y + (h - len(lineas) * paso) / 2 if valinea == "middle" else y + 8
        margen = 0 if alinea == "center" else 10
        for i, linea in enumerate(lineas):
            if linea.strip():
                caja(f"{nombre} l{i}", x + margen, y0 + i * paso, w - 2 * margen, paso, linea,
                     fondo="transparent", borde="transparent", ancho_borde=0, tam=tam,
                     color=color if i == 0 else (TEXTO_2 if len(lineas) > 2 else color),
                     alinea=alinea, valinea="middle", radio=0)
        return
    cfg = {"color": {"fixed": color}, "size": tam, "align": alinea, "valign": valinea}
    if texto_campo:
        cfg["text"] = {"mode": "field", "field": texto_campo, "fixed": ""}
    else:
        cfg["text"] = {"mode": "fixed", "fixed": texto}
    elementos.append({
        "type": "rectangle", "name": nombre,
        "config": cfg,
        "constraint": {"horizontal": "left", "vertical": "top"},
        "placement": {"left": x, "top": y, "width": w, "height": h},
        "background": {"color": {"fixed": fondo}},
        "border": {"color": _color(borde, campo_borde), "width": ancho_borde, "radius": radio},
    })


def punto(nombre, x, y, campo, d=9):
    """Círculo pequeño cuyo color sigue la sonda HTTP."""
    elementos.append({
        "type": "ellipse", "name": nombre,
        "config": {"text": {"mode": "fixed", "fixed": ""}, "color": {"fixed": TEXTO}},
        "constraint": {"horizontal": "left", "vertical": "top"},
        "placement": {"left": x, "top": y, "width": d, "height": d},
        "background": {"color": _color("#6e7681", campo)},
        "border": {"color": {"fixed": FONDO}, "width": 1},
    })


def linea_h(nombre, x1, x2, y, color=LINEA, grosor=3):
    caja(nombre, x1, y, x2 - x1, grosor, fondo=color, borde=color, ancho_borde=0, radio=0)


def linea_v(nombre, x, y1, y2, color=LINEA, grosor=3):
    caja(nombre, x, y1, grosor, y2 - y1, fondo=color, borde=color, ancho_borde=0, radio=0)


def texto(nombre, x, y, w, h, t, tam=12, color=TEXTO, alinea="left", campo=None):
    caja(nombre, x, y, w, h, texto=t, fondo="transparent", borde="transparent", ancho_borde=0,
         tam=tam, color=color, alinea=alinea, valinea="middle", radio=0, texto_campo=campo)


def metricas(host, x, y):
    """CPU y RAM del host (node_exporter), en dos textos pequeños."""
    texto(f"cpu-et {host}", x, y, 34, 16, "CPU", 10, TEXTO_2)
    texto(f"cpu {host}", x + 32, y, 40, 16, "", 11, TEXTO, campo=f"cpu:{host}")
    texto(f"ram-et {host}", x + 74, y, 34, 16, "RAM", 10, TEXTO_2)
    texto(f"ram {host}", x + 106, y, 40, 16, "", 11, TEXTO, campo=f"ram:{host}")


def rejilla(host, items, x0, y0, cols, w=116, h=34, sep=6):
    """Cuadrícula de contenedores. Devuelve la altura que ocupa."""
    for i, (nombre, etiqueta, sonda) in enumerate(items):
        x = x0 + (i % cols) * (w + sep)
        y = y0 + (i // cols) * (h + sep)
        caja(f"{host}/{nombre}", x, y, w, h, etiqueta, fondo=CAJA_2, ancho_borde=2,
             campo_borde=f"ct:{host}/{nombre}", tam=11, alinea="center", valinea="middle", radio=5)
        if sonda:
            punto(f"web {host}/{nombre}", x + w - 12, y + 3, f"svc:{sonda}")
    filas = -(-len(items) // cols)
    return filas * (h + sep)


# ── Cabecera ────────────────────────────────────────────────────────────────────
texto("título", 10, 6, 600, 30, "Homelab · mapa de infraestructura", 20, TEXTO)
texto("subtítulo", 10, 34, 700, 18,
      "Borde verde/rojo: estado en vivo (Prometheus). Punto en la esquina: la web responde (Blackbox).",
      11, TEXTO_2)

# ── Internet y router del ISP ───────────────────────────────────────────────────
caja("internet", 760, 20, 170, 46, "Internet\nfibra · IPv4", fondo="#13233d", borde="#2b4a7a",
     tam=12, alinea="center", valinea="middle", radio=23)
caja("router isp", 960, 20, 240, 46, "Router del ISP\ntelefonía y wifi de casa", fondo=CAJA,
     tam=12, alinea="center", valinea="middle")
linea_h("isp-enlace", 930, 960, 42)
linea_v("isp-fw", 1080, 66, 110)

# ── pve-router + fw-01 ──────────────────────────────────────────────────────────
caja("pve-router", 700, 110, 520, 190, "", fondo=CAJA, ancho_borde=2, campo_borde="host:pve-router")
texto("pve-router t", 716, 114, 260, 24, "pve-router", 16, TEXTO)
texto("pve-router s", 716, 136, 300, 16, "Proxmox VE · nodo del clúster · INFRA", 11, TEXTO_2)
metricas("pve-router", 1040, 118)
caja("fw-01", 716, 168, 488, 120,
     "fw-01  ·  OPNsense (VM 100)\n\nFirewall de VLAN y NAT · DHCP y Unbound DNS\n"
     "WireGuard → ProtonVPN · Tailscale (subnet router)",
     fondo=CAJA_2, ancho_borde=2, campo_borde="vm:fw-01", tam=12, valinea="top", radio=6)
punto("web OPNsense", 1186, 174, "svc:OPNsense")
linea_v("trunk", 958, 300, 346, "#cbd5e1", 5)

# ── Switch y VLAN ───────────────────────────────────────────────────────────────
caja("switch", 770, 346, 380, 58, "TL-SG108E · switch gestionable 8 × GbE · 802.1Q\n"
     "P1 trunk · P2 pve-aux · P3 wks-02 · P4 pve-main · P6 nas-01 · P8 wks-01",
     fondo=CAJA, ancho_borde=2, borde="#3b9eff", tam=11, alinea="center", valinea="middle")
x = 1190
for vid, col in VLAN.items():
    caja(f"vlan {vid}", x, 360, 42, 22, str(vid), fondo=col, borde=col, ancho_borde=0, tam=11,
         color="#0d1117", alinea="center", valinea="middle", radio=4)
    x += 48
texto("vlan et", 1190, 386, 560, 16, "5 INFRA · 10 MGMT · 15 AI · 20 DEVICES · 30 SRV · 40 GAME · 50 IOT",
      10, TEXTO_2)

# ── Bus hacia los hosts ─────────────────────────────────────────────────────────
Y_BUS = 436
Y_HOSTS = 470
linea_v("sw-bus", 958, 404, Y_BUS, "#cbd5e1", 5)
linea_h("bus", 110, 1520, Y_BUS, "#cbd5e1", 4)
for nombre, cx in (("wks", 110), ("nas", 540), ("pve-main", 1080), ("pve-aux", 1520)):
    linea_v(f"bus {nombre}", cx, Y_BUS, Y_HOSTS, "#cbd5e1", 4)

# ── Estaciones de trabajo (sin métricas) ────────────────────────────────────────
caja("wks-02", 10, Y_HOSTS, 200, 86, "wks-02\nPC de administración · INFRA", fondo=CAJA,
     tam=12, valinea="middle", alinea="center")
caja("wks-01", 10, Y_HOSTS + 100, 200, 86, "wks-01\nPC de gaming · INFRA", fondo=CAJA,
     tam=12, valinea="middle", alinea="center")

# ── nas-01 ──────────────────────────────────────────────────────────────────────
COLS_NAS = 5
alto_nas = 120 + -(-len(NAS) // COLS_NAS) * 40 + 28
caja("nas-01", 230, Y_HOSTS, 620, alto_nas, "", fondo=CAJA, ancho_borde=2, campo_borde="host:nas-01")
texto("nas-01 t", 246, Y_HOSTS + 4, 300, 24, "nas-01", 16, TEXTO)
texto("nas-01 s", 246, Y_HOSTS + 26, 360, 16, "TrueNAS Scale · bare metal · INFRA + SRV (macvlan)", 11, TEXTO_2)
metricas("nas-01", 690, Y_HOSTS + 8)
texto("nas-01 z", 246, Y_HOSTS + 50, 590, 30,
      "ZFS: boot-pool (SSD) · vault (2 SSD, espejo) · tank (2 HDD, stripe)", 11, NARANJA)
texto("nas-01 d", 246, Y_HOSTS + 92, 300, 16, "DOCKER · MACVLAN EN SRV", 10, "#2ed9a0")
rejilla("nas-01", NAS, 246, Y_HOSTS + 112, COLS_NAS)

# ── pve-main + docker-main + k3s-01 ─────────────────────────────────────────────
X_PM = 870
alto_dm = 56 + -(-len(DOCKER_MAIN) // 3) * 40 + 8
alto_pm = 78 + alto_dm + 90
caja("pve-main", X_PM, Y_HOSTS, 420, alto_pm, "", fondo=CAJA, ancho_borde=2, campo_borde="host:pve-main")
texto("pve-main t", X_PM + 16, Y_HOSTS + 4, 200, 24, "pve-main", 16, TEXTO)
texto("pve-main s", X_PM + 16, Y_HOSTS + 26, 260, 16, "Proxmox VE · nodo del clúster", 11, TEXTO_2)
metricas("pve-main", X_PM + 250, Y_HOSTS + 8)
caja("docker-main", X_PM + 12, Y_HOSTS + 52, 396, alto_dm, "", fondo=CAJA_2, ancho_borde=2,
     campo_borde="vm:docker-main")
texto("docker-main t", X_PM + 24, Y_HOSTS + 56, 360, 18,
      "docker-main · CT 200 · LXC · SRV", 12, TEXTO)
rejilla("docker-main", DOCKER_MAIN, X_PM + 24, Y_HOSTS + 80, 3, w=118)
y_k3s = Y_HOSTS + 52 + alto_dm + 12
caja("k3s-01", X_PM + 12, y_k3s, 396, 64,
     "k3s-01 · VM 300 · laboratorio DevOps\nSe enciende bajo demanda: rojo = apagada",
     fondo=CAJA_2, ancho_borde=2, campo_borde="vm:k3s-01", tam=11, valinea="middle", alinea="center")

# ── pve-aux + docker-aux ────────────────────────────────────────────────────────
X_PA = 1310
alto_da = 56 + -(-len(DOCKER_AUX) // 3) * 40 + 8
alto_pa = 78 + alto_da + 10
caja("pve-aux", X_PA, Y_HOSTS, 420, alto_pa, "", fondo=CAJA, ancho_borde=2, campo_borde="host:pve-aux")
texto("pve-aux t", X_PA + 16, Y_HOSTS + 4, 200, 24, "pve-aux", 16, TEXTO)
texto("pve-aux s", X_PA + 16, Y_HOSTS + 26, 260, 16, "Proxmox VE · nodo del clúster", 11, TEXTO_2)
metricas("pve-aux", X_PA + 250, Y_HOSTS + 8)
caja("docker-aux", X_PA + 12, Y_HOSTS + 52, 396, alto_da, "", fondo=CAJA_2, ancho_borde=2,
     campo_borde="vm:docker-aux")
texto("docker-aux t", X_PA + 24, Y_HOSTS + 56, 360, 18,
      "docker-aux · CT 201 · LXC · SRV · monitorización", 12, TEXTO)
rejilla("docker-aux", DOCKER_AUX, X_PA + 24, Y_HOSTS + 80, 3, w=118)

# Clúster Proxmox: marco naranja que rodea a pve-main y pve-aux
alto_cl = max(alto_pm, alto_pa)
caja("clúster", X_PM - 10, Y_HOSTS - 10, 1310 + 420 - 870 + 20, alto_cl + 36, "", fondo="transparent",
     borde=NARANJA, ancho_borde=1, radio=8)
# El marco va al fondo para no tapar los conectores del bus ni las cajas de los nodos
elementos.insert(0, elementos.pop())
texto("clúster t", X_PM, Y_HOSTS + alto_cl + 6, 760, 16,
      "Clúster Proxmox VE de 3 nodos (pve-router, pve-main y pve-aux)", 11, NARANJA)

# ── Consultas: una por familia, con el nombre del campo en la leyenda ───────────
DS = {"type": "prometheus", "uid": "prometheus"}


def consulta(ref, expr, leyenda):
    return {"refId": ref, "datasource": DS, "expr": expr, "legendFormat": leyenda,
            "instant": True, "range": False}


targets = [
    consulta("A", 'up{job="node"}', "host:{{host}}"),
    consulta("B", 'pve_up{id=~"qemu/.*|lxc/.*"} * on(id) group_left(name) pve_guest_info',
             "vm:{{name}}"),
    consulta("C", '(time() - max by (host, name) (container_last_seen{name!=""})) < bool 120',
             "ct:{{host}}/{{name}}"),
    consulta("D", "probe_success", "svc:{{service}}"),
    consulta("E", '100 - avg by (host) (rate(node_cpu_seconds_total{job="node",mode="idle"}[5m])) * 100',
             "cpu:{{host}}"),
    consulta("F", '100 * (1 - node_memory_MemAvailable_bytes{job="node"} / node_memory_MemTotal_bytes{job="node"})',
             "ram:{{host}}"),
]

panel = {
    "id": 1,
    "type": "canvas",
    "title": "",
    "transparent": True,
    "datasource": DS,
    "gridPos": {"x": 0, "y": 0, "w": 24, "h": 29},
    "targets": targets,
    "transformations": [{"id": "joinByField", "options": {"byField": "Time", "mode": "outer"}}],
    "fieldConfig": {
        "defaults": {
            "color": {"mode": "thresholds"},
            "thresholds": {"mode": "absolute",
                           "steps": [{"color": "red", "value": None}, {"color": "green", "value": 1}]},
            "mappings": [],
        },
        "overrides": [{
            "matcher": {"id": "byRegexp", "options": "^(cpu|ram):.*"},
            "properties": [{"id": "unit", "value": "percent"}, {"id": "decimals", "value": 0}],
        }],
    },
    "options": {
        "inlineEditing": False,
        "showAdvancedTypes": False,
        "panZoom": True,
        "infinitePan": False,
        "root": {
            "type": "frame", "name": "Mapa",
            "background": {"color": {"fixed": FONDO}},
            "border": {"color": {"fixed": "transparent"}},
            "constraint": {"horizontal": "left", "vertical": "top"},
            "placement": {"left": 0, "top": 0, "width": 100, "height": 100, "rotation": 0},
            "elements": elementos,
        },
    },
}

dashboard = {
    "uid": "homelab-mapa",
    "title": "Homelab · Mapa",
    "tags": ["homelab", "mapa"],
    "timezone": "browser",
    "schemaVersion": 39,
    "version": 1,
    "refresh": "1m",
    "time": {"from": "now-1h", "to": "now"},
    "editable": False,
    "templating": {"list": []},
    "panels": [panel],
}

SALIDA.write_text(json.dumps(dashboard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"{SALIDA.name}: {len(elementos)} elementos, {len(targets)} consultas")
