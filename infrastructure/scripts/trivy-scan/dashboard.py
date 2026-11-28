"""Genera el dashboard de Grafana de las métricas trivy_scan_* (Homelab · Vulnerabilidades).

Uso: python3 infrastructure/scripts/trivy-scan/dashboard.py \\
       infrastructure/ansible/roles/grafana/files/dashboards/homelab-vulnerabilidades.json
Después, relanzar el rol grafana (los dashboards no se editan en la interfaz).
"""
import json
import sys

DS = {"type": "prometheus", "uid": "prometheus"}
F = 'hosts=~".*$host.*"'  # la etiqueta hosts lleva la lista de hosts donde corre la imagen
V = "trivy_scan_vulnerabilities"
panels = []


def add(p):
    p["id"] = len(panels) + 1
    p["datasource"] = DS
    for t in p.get("targets", []):
        t["datasource"] = DS
    panels.append(p)


def stat(title, expr, x, w, desc, unit=None, steps=None, decimals=None):
    d = {"thresholds": {"mode": "absolute", "steps": steps or [{"color": "text", "value": None}]}}
    if unit:
        d["unit"] = unit
    if decimals is not None:
        d["decimals"] = decimals
    add({"type": "stat", "title": title, "description": desc,
         "gridPos": {"x": x, "y": 0, "w": w, "h": 4},
         "targets": [{"expr": expr, "refId": "A", "instant": True, "range": False}],
         "fieldConfig": {"defaults": d, "overrides": []},
         "options": {"colorMode": "value", "graphMode": "none", "textMode": "value",
                     "reduceOptions": {"calcs": ["lastNotNull"]}}})


stat("CRITICAL con arreglo", f'sum({V}{{severity="CRITICAL",{F}}}) or vector(0)', 0, 4,
     "Suma de CVE CRITICAL con arreglo publicado en todas las imágenes en marcha. Siempre habrá alguna en imágenes grandes: lo que importa es la tendencia.",
     steps=[{"color": "green", "value": None}, {"color": "red", "value": 1}])
stat("HIGH con arreglo", f'sum({V}{{severity="HIGH",{F}}}) or vector(0)', 4, 4,
     "Suma de CVE HIGH con arreglo publicado.",
     steps=[{"color": "green", "value": None}, {"color": "orange", "value": 1}])
stat("Imágenes escaneadas", 'count(trivy_scan_image_unscanned == 0) or vector(0)', 8, 4,
     "Imágenes en marcha (según cAdvisor) que Trivy pudo escanear en la última pasada.")
stat("Sin escanear", 'count(trivy_scan_image_unscanned == 1) or vector(0)', 12, 4,
     "Imágenes que fallaron (registro sin acceso, límite de peticiones, tiempo). El motivo está en el informe de /srv/trivy-scan/informes/.",
     steps=[{"color": "green", "value": None}, {"color": "orange", "value": 1}])
stat("Hosts sin datos", 'max(trivy_scan_hosts_missing) or vector(0)', 16, 4,
     "Hosts Docker cuyo cAdvisor estaba caído durante el escaneo: sus imágenes no entraron.",
     steps=[{"color": "green", "value": None}, {"color": "red", "value": 1}])
stat("Último escaneo", 'time() - max(trivy_scan_last_run_timestamp_seconds)', 20, 4,
     "Tiempo desde el último escaneo completo. Corre los sábados a las 07:00: más de 8 días es que el timer no ha corrido.",
     unit="s", decimals=0,
     steps=[{"color": "green", "value": None}, {"color": "orange", "value": 8 * 86400}, {"color": "red", "value": 15 * 86400}])


def top(title, sev, x, color, desc):
    add({"type": "bargauge", "title": title, "description": desc,
         "gridPos": {"x": x, "y": 4, "w": 12, "h": 10},
         "targets": [{"expr": f'topk(10, max by (image, hosts) ({V}{{severity="{sev}",{F}}}) > 0)',
                      "refId": "A", "instant": True, "range": False,
                      "legendFormat": "{{image}} · {{hosts}}"}],
         "fieldConfig": {"defaults": {"min": 0, "decimals": 0,
                                      "color": {"mode": "fixed", "fixedColor": color}},
                         "overrides": []},
         "options": {"orientation": "horizontal", "displayMode": "basic", "showUnfilled": True,
                     "valueMode": "text", "namePlacement": "top",
                     "reduceOptions": {"calcs": ["lastNotNull"]}}})


top("Imágenes con más CRITICAL", "CRITICAL", 0, "red",
    "Las diez imágenes con más CVE CRITICAL con arreglo. El remedio habitual es subir la versión cuando diun avise.")
top("Imágenes con más HIGH", "HIGH", 12, "orange",
    "Las diez imágenes con más CVE HIGH con arreglo.")


def trend(title, sev, x, color, desc):
    add({"type": "timeseries", "title": title, "description": desc,
         "gridPos": {"x": x, "y": 14, "w": 12, "h": 8},
         "targets": [{"expr": f'sum({V}{{severity="{sev}",{F}}})', "refId": "A",
                      "legendFormat": sev}],
         "fieldConfig": {"defaults": {"min": 0, "decimals": 0,
                                      "color": {"mode": "fixed", "fixedColor": color},
                                      "custom": {"lineWidth": 2, "fillOpacity": 10,
                                                 "lineInterpolation": "stepAfter",
                                                 "showPoints": "never", "spanNulls": True}},
                         "overrides": []},
         "options": {"legend": {"showLegend": False},
                     "tooltip": {"mode": "single"}}})


trend("Evolución de CRITICAL", "CRITICAL", 0, "red",
      "Total de CRITICAL con arreglo por escaneo (escalón semanal). Sube con imágenes nuevas o CVE nuevos; baja al actualizar.")
trend("Evolución de HIGH", "HIGH", 12, "orange", "Total de HIGH con arreglo por escaneo.")

add({"type": "table", "title": "Todas las imágenes",
     "description": "Una fila por imagen en marcha, con los hosts donde corre. Ordenable por columna.",
     "gridPos": {"x": 0, "y": 22, "w": 24, "h": 14},
     "targets": [
         {"expr": f'max by (image, hosts) ({V}{{severity="CRITICAL",{F}}})', "refId": "A",
          "instant": True, "range": False, "format": "table"},
         {"expr": f'max by (image, hosts) ({V}{{severity="HIGH",{F}}})', "refId": "B",
          "instant": True, "range": False, "format": "table"}],
     "transformations": [
         {"id": "merge", "options": {}},
         {"id": "organize", "options": {
             "excludeByName": {"Time": True},
             "indexByName": {"image": 0, "hosts": 1, "Value #A": 2, "Value #B": 3},
             "renameByName": {"image": "Imagen", "hosts": "Hosts",
                              "Value #A": "CRITICAL", "Value #B": "HIGH"}}},
         {"id": "sortBy", "options": {"sort": [{"field": "CRITICAL", "desc": True}]}}],
     "fieldConfig": {"defaults": {"custom": {"align": "auto"}}, "overrides": [
         {"matcher": {"id": "byName", "options": "CRITICAL"}, "properties": [
             {"id": "custom.cellOptions", "value": {"type": "color-text"}},
             {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                 {"color": "text", "value": None}, {"color": "red", "value": 1}]}},
             {"id": "custom.width", "value": 110}]},
         {"matcher": {"id": "byName", "options": "HIGH"}, "properties": [
             {"id": "custom.cellOptions", "value": {"type": "color-text"}},
             {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                 {"color": "text", "value": None}, {"color": "orange", "value": 1}]}},
             {"id": "custom.width", "value": 110}]},
         {"matcher": {"id": "byName", "options": "Hosts"}, "properties": [
             {"id": "custom.width", "value": 260}]}]},
     "options": {"showHeader": True, "cellHeight": "sm"}})

add({"type": "table", "title": "Sin escanear",
     "description": "Imágenes que fallaron en la última pasada. El motivo está en el informe del host.",
     "gridPos": {"x": 0, "y": 36, "w": 24, "h": 5},
     "targets": [{"expr": "trivy_scan_image_unscanned == 1", "refId": "A", "instant": True,
                  "range": False, "format": "table"}],
     "transformations": [{"id": "organize", "options": {
         "excludeByName": {"Time": True, "Value": True, "__name__": True, "host": True,
                           "instance": True, "job": True},
         "renameByName": {"image": "Imagen"}}}],
     "fieldConfig": {"defaults": {}, "overrides": []},
     "options": {"showHeader": True, "cellHeight": "sm"}})

dash = {
    "uid": "homelab-vulnerabilidades",
    "title": "Homelab · Vulnerabilidades",
    "description": "CVE con arreglo publicado en las imágenes que corren en los hosts Docker, del escaneo semanal con Trivy (rol trivy_scan).",
    "tags": ["homelab", "seguridad", "trivy"],
    "timezone": "browser",
    "schemaVersion": 39,
    "version": 1,
    "refresh": "1h",
    "time": {"from": "now-30d", "to": "now"},
    "templating": {"list": [{
        "name": "host", "label": "Host", "type": "custom",
        "query": "docker-main,docker-aux,nas-01",
        "multi": False, "includeAll": True, "allValue": "",
        "current": {"selected": True, "text": "All", "value": "$__all"},
        "options": []}]},
    "editable": False,
    "panels": panels,
}
json.dump(dash, open(sys.argv[1], "w", encoding="utf-8", newline="\n"), ensure_ascii=False, indent=2)
print(len(panels), "paneles")
