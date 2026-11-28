#!/usr/bin/env python3
"""Escaneo semanal con Trivy de las imágenes que corren en los hosts Docker.

- La lista de imágenes en marcha sale de Prometheus: cAdvisor corre en cada host Docker y su
  métrica `container_last_seen` lleva la imagen y la etiqueta `host`. Sin SSH ni acceso a los
  sockets de Docker de otros hosts. El K3s no entra (job distinto): lo cubre Trivy Operator.
- Escanea cada imagen una sola vez, aunque corra en varios hosts, con Trivy en contenedor y
  `--image-src remote`: la baja del registro por su tag (los composes fijan versión, así que es
  la que corre). Solo vulnerabilidades SEVERIDAD con arreglo publicado (`--ignore-unfixed`).
  Trivy guarda en DATA_DIR/trivy el análisis de cada capa: de una semana a otra solo descarga
  y analiza las capas nuevas.
- Escribe el informe en DATA_DIR/informes/AAAA-MM-DD.md (se guardan INFORMES_MAX), las métricas
  en TEXTFILE_DIR/trivy_scan.prom para el node_exporter del host y el resumen a ntfy, con la
  diferencia frente al escaneo anterior (DATA_DIR/estado.json).

Lo lanza un timer de systemd en docker-aux (rol de Ansible `trivy_scan`). Solo lee: no cambia
nada en los hosts. Las imágenes construidas en local (sin registro, p. ej. `salud:local`) no se
pueden bajar: salen como no escaneadas; IGNORAR las quita del todo.
Configuración: /srv/trivy-scan/trivy-scan.env (la escribe el rol; ver trivy-scan.env.example)
Uso: trivy-scan.py [--sin-ntfy] [--solo IMAGEN]   (--solo escanea una imagen y no guarda nada)
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import time
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


ENV = load_env(os.environ.get("ENV_FILE", "/srv/trivy-scan/trivy-scan.env"))
NTFY_URL = ENV["NTFY_URL"]
NTFY_TOPIC = ENV.get("NTFY_TOPIC", "homelab-actualizaciones")
PROMETHEUS_URL = ENV["PROMETHEUS_URL"].rstrip("/")
CADVISOR_JOB = ENV.get("CADVISOR_JOB", "cadvisor")
TRIVY_IMAGE = ENV.get("TRIVY_IMAGE", "aquasec/trivy:0.76.2")
DATA_DIR = ENV.get("DATA_DIR", "/srv/trivy-scan")
INFORMES_DIR = os.path.join(DATA_DIR, "informes")
INFORMES_MAX = int(ENV.get("INFORMES_MAX", "8"))
TEXTFILE_DIR = ENV.get("TEXTFILE_DIR", "")
SEVERIDAD = ENV.get("SEVERIDAD", "HIGH,CRITICAL")
IGNORAR = {i for i in ENV.get("IGNORAR", "").split(",") if i}
TIMEOUT_IMAGEN = int(ENV.get("TIMEOUT_IMAGEN", "600"))
TOPE_TOTAL = int(ENV.get("TOPE_TOTAL", "10800"))  # las que no quepan salen como no escaneadas
ESTADO = os.path.join(DATA_DIR, "estado.json")


def prometheus(query):
    url = f"{PROMETHEUS_URL}/api/v1/query?" + urllib.parse.urlencode({"query": query})
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)["data"]["result"]


def imagenes_en_marcha():
    """Devuelve ({imagen: [hosts]}, [hosts con cAdvisor caído])."""
    caidos = [x["metric"].get("host", x["metric"]["instance"])
              for x in prometheus(f'up{{job="{CADVISOR_JOB}"}} == 0')]
    hosts_de = {}
    for x in prometheus(f'count by (host, image) (container_last_seen{{job="{CADVISOR_JOB}", image!=""}})'):
        hosts_de.setdefault(x["metric"]["image"], set()).add(x["metric"].get("host", "?"))
    # El propio Trivy sale si cAdvisor lo vio hace poco (series de hasta 5 min tras parar)
    ignorar = IGNORAR | {TRIVY_IMAGE}
    return {i: sorted(h) for i, h in hosts_de.items() if i not in ignorar}, caidos


def corto(imagen):
    """Nombre para ntfy y títulos: sin registro ni digest."""
    return imagen.split("@")[0].split("/")[-1]


def trivy(*args, timeout):
    cmd = ["docker", "run", "--rm", "-v", f"{DATA_DIR}/trivy:/root/.cache/trivy",
           "-e", "TMPDIR=/root/.cache/trivy/tmp", TRIVY_IMAGE, *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def escanear(imagen, reintentos=3):
    """Devuelve {"CRITICAL": [...], "HIGH": [...]} o un str con el error."""
    for intento in range(reintentos):
        try:
            r = trivy("image", "--image-src", "remote", "--scanners", "vuln", "--severity", SEVERIDAD,
                      "--ignore-unfixed", "--skip-db-update", "--format", "json", "--quiet", imagen,
                      timeout=TIMEOUT_IMAGEN)
        except subprocess.TimeoutExpired:
            return f"más de {TIMEOUT_IMAGEN // 60} min"
        # Límite de peticiones del registro (ghcr.io, lscr.io, Docker Hub): esperar y reintentar
        if r.returncode != 0 and "TOOMANYREQUESTS" in r.stderr and intento < reintentos - 1:
            time.sleep(60 * (intento + 1))
            continue
        break
    if r.returncode != 0:
        lineas = [li.strip() for li in r.stderr.strip().splitlines() if li.strip()]
        return (lineas[-1] if lineas else f"código {r.returncode}")[:200]
    try:
        datos = json.loads(r.stdout)
    except ValueError:
        return "salida de Trivy no es JSON"
    vulns, vistos = {}, set()
    for res in datos.get("Results") or []:
        for v in res.get("Vulnerabilities") or []:
            clave = (v["VulnerabilityID"], v["PkgName"])
            if clave in vistos:
                continue
            vistos.add(clave)
            vulns.setdefault(v["Severity"], []).append({
                "id": v["VulnerabilityID"], "paquete": v["PkgName"],
                "instalada": v.get("InstalledVersion", ""), "arreglo": v.get("FixedVersion", ""),
                "titulo": (v.get("Title") or "")[:90]})
    return vulns


def notify(prioridad, etiquetas, titulo, mensaje):
    msg = {"topic": NTFY_TOPIC, "priority": prioridad, "tags": etiquetas, "title": titulo, "message": mensaje}
    req = urllib.request.Request(NTFY_URL, data=json.dumps(msg).encode(), headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10)


def contar(r, s):
    return len(r.get(s, [])) if isinstance(r, dict) else 0


def informe(fecha, resultados, hosts_de, caidos, anterior):
    orden = sorted(resultados, key=lambda i: (-contar(resultados[i], "CRITICAL"), -contar(resultados[i], "HIGH"), i))
    L = [f"# Escaneo de imágenes {fecha}", "",
         f"Trivy `{TRIVY_IMAGE.split(':')[-1]}` · severidad {SEVERIDAD} con arreglo publicado · "
         f"{len(resultados)} imágenes", ""]
    if caidos:
        L += [f"**Hosts sin datos (cAdvisor caído):** {', '.join(caidos)}", ""]
    L += ["| Imagen | Hosts | CRITICAL | HIGH | Antes (C/H) |", "|---|---|---|---|---|"]
    for i in orden:
        r = resultados[i]
        antes = anterior.get(i)
        antes_txt = f"{antes[0]}/{antes[1]}" if antes else "nueva"
        if isinstance(r, dict):
            L.append(f"| `{i}` | {', '.join(hosts_de[i])} | {contar(r, 'CRITICAL')} | {contar(r, 'HIGH')} | {antes_txt} |")
        else:
            L.append(f"| `{i}` | {', '.join(hosts_de[i])} | — | — | sin escanear: {r} |")
    for i in orden:
        r = resultados[i]
        if not isinstance(r, dict) or not r.get("CRITICAL"):
            continue
        L += ["", f"## {i}", "", "| CVE | Paquete | Instalada | Arreglo | Título |", "|---|---|---|---|---|"]
        for v in r["CRITICAL"]:
            L.append(f"| {v['id']} | {v['paquete']} | {v['instalada']} | {v['arreglo']} | {v['titulo']} |")
    L += ["", "Las HIGH de una imagen: `trivy-scan.py --solo <imagen>`.", ""]
    return "\n".join(L), orden


def metricas(resultados, hosts_de, caidos):
    if not TEXTFILE_DIR:
        return
    esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')  # noqa: E731
    L = ["# HELP trivy_scan_vulnerabilities CVE con arreglo publicado en la imagen, por severidad",
         "# TYPE trivy_scan_vulnerabilities gauge"]
    for i, r in sorted(resultados.items()):
        if isinstance(r, dict):
            for s in SEVERIDAD.split(","):
                L.append(f'trivy_scan_vulnerabilities{{image="{esc(i)}",hosts="{",".join(hosts_de[i])}",'
                         f'severity="{s}"}} {contar(r, s)}')
    L += ["# HELP trivy_scan_image_unscanned 1 si la imagen no se pudo escanear",
          "# TYPE trivy_scan_image_unscanned gauge"]
    L += [f'trivy_scan_image_unscanned{{image="{esc(i)}"}} {0 if isinstance(r, dict) else 1}'
          for i, r in sorted(resultados.items())]
    L += ["# HELP trivy_scan_hosts_missing Hosts Docker sin datos de cAdvisor en el último escaneo",
          "# TYPE trivy_scan_hosts_missing gauge", f"trivy_scan_hosts_missing {len(caidos)}",
          "# HELP trivy_scan_last_run_timestamp_seconds Fin del último escaneo",
          "# TYPE trivy_scan_last_run_timestamp_seconds gauge",
          f"trivy_scan_last_run_timestamp_seconds {int(time.time())}", ""]
    tmp = os.path.join(TEXTFILE_DIR, ".trivy_scan.prom.tmp")
    with open(tmp, "w") as f:
        f.write("\n".join(L))
    os.chmod(tmp, 0o644)
    os.replace(tmp, os.path.join(TEXTFILE_DIR, "trivy_scan.prom"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sin-ntfy", action="store_true")
    ap.add_argument("--solo")
    args = ap.parse_args()
    os.makedirs(f"{DATA_DIR}/trivy/tmp", exist_ok=True)
    os.makedirs(INFORMES_DIR, exist_ok=True)

    r = trivy("image", "--download-db-only", "--quiet", timeout=900)
    if r.returncode != 0:
        raise RuntimeError("no se pudo bajar la base de Trivy: "
                           + (r.stderr.strip().splitlines() or ["sin detalle"])[-1][:200])

    if args.solo:
        print(json.dumps(escanear(args.solo), indent=2, ensure_ascii=False))
        return

    hosts_de, caidos = imagenes_en_marcha()
    if not hosts_de:
        raise RuntimeError("Prometheus no devuelve ninguna imagen en marcha")

    resultados = {}
    limite = time.monotonic() + TOPE_TOTAL
    for i in sorted(hosts_de):
        if time.monotonic() > limite:
            resultados[i] = f"tope de {TOPE_TOTAL // 3600} h alcanzado"
            continue
        try:
            resultados[i] = escanear(i)
        except (subprocess.SubprocessError, OSError, KeyError) as e:
            resultados[i] = f"error: {e}"[:200]

    anterior = {}
    if os.path.exists(ESTADO):
        with open(ESTADO) as f:
            anterior = json.load(f)
    fecha = datetime.date.today().isoformat()
    texto, orden = informe(fecha, resultados, hosts_de, caidos, anterior)
    ruta = os.path.join(INFORMES_DIR, f"{fecha}.md")
    with open(ruta, "w") as f:
        f.write(texto)
    informes = sorted(n for n in os.listdir(INFORMES_DIR) if n.endswith(".md"))
    for viejo in informes[:-INFORMES_MAX]:
        os.remove(os.path.join(INFORMES_DIR, viejo))
    metricas(resultados, hosts_de, caidos)

    cuenta = {i: [contar(r, "CRITICAL"), contar(r, "HIGH")] for i, r in resultados.items() if isinstance(r, dict)}
    with open(ESTADO, "w") as f:
        json.dump(cuenta, f, indent=1)

    total_c = sum(c for c, _ in cuenta.values())
    total_h = sum(h for _, h in cuenta.values())
    antes_c = sum(c for c, _ in anterior.values()) if anterior else None
    sin = [i for i, r in resultados.items() if not isinstance(r, dict)]
    peores = [i for i in orden if i in cuenta and sum(cuenta[i])][:6]
    lineas = [f"{total_c} CRITICAL y {total_h} HIGH con arreglo en {len(cuenta)} imágenes"
              + (f" (antes {antes_c} CRITICAL)" if antes_c is not None else "") + "."]
    lineas += [f"• {corto(i)}: {cuenta[i][0]} C, {cuenta[i][1]} H" for i in peores]
    if sin:
        lineas.append(f"Sin escanear: {', '.join(corto(s) for s in sin)}")
    if caidos:
        lineas.append(f"Hosts sin datos: {', '.join(caidos)}")
    lineas.append(f"Informe: {ruta}")
    print("\n".join(lineas))
    if not args.sin_ntfy:
        # Siempre habrá CRITICAL en imágenes grandes: la prioridad sube solo si empeora o falta un host
        empeora = antes_c is not None and total_c > antes_c
        notify(3 if empeora or caidos else 2, ["shield"], "Escaneo semanal de imágenes", "\n".join(lineas))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # el timer no avisa si el script muere: que llegue a ntfy
        try:
            notify(4, ["warning"], "Escaneo de imágenes fallido", f"{type(e).__name__}: {e}"[:300])
        finally:
            sys.exit(f"{type(e).__name__}: {e}")
