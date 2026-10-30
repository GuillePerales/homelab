#!/usr/bin/env python3
"""Crea citas en el calendario de iCloud (CalDAV), por HTTP o por línea de comandos.

  agenda.py cita "Título" AAAA-MM-DD [HH:MM [HH:MM]] [calendario]
  agenda.py proximos [días]
  agenda.py run          servidor HTTP (modo contenedor)

HTTP: GET /health · GET /calendarios · GET /proximos?dias=7
      POST /cita {"titulo", "fecha", "inicio"?, "fin"?, "calendario"?, "ubicacion"?}

Sin inicio la cita es de todo el día. Configuración por variables de entorno
(ver .env.example); sin ICLOUD_USER/ICLOUD_PASS lee ~/.icloud-caldav
(línea 1: Apple ID, línea 2: contraseña de app).
"""
import datetime as dt
import json
import os
import sys
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

import caldav

TZ = ZoneInfo(os.environ.get("TZ", "Europe/Madrid"))
CALENDARIOS = [c.strip() for c in os.environ.get("CALENDARIOS", "Eventos").split(",") if c.strip()]
DEFECTO = os.environ.get("CALENDARIO_DEFECTO", CALENDARIOS[0])
PUERTO = int(os.environ.get("PUERTO", "8080"))


def credenciales():
    user, pwd = os.environ.get("ICLOUD_USER"), os.environ.get("ICLOUD_PASS")
    if not (user and pwd):
        user, pwd = [l.strip() for l in (Path.home() / ".icloud-caldav").read_text(encoding="utf8").splitlines()[:2]]
    return user, pwd


def a_local(valor):
    """Devuelve (datetime local, todo_el_dia) para un DTSTART/DTEND de iCalendar."""
    if isinstance(valor, dt.datetime):
        return (valor.replace(tzinfo=TZ) if valor.tzinfo is None else valor.astimezone(TZ)), False
    return dt.datetime.combine(valor, dt.time(), tzinfo=TZ), True


def proximos(dias):
    """Eventos desde hoy hasta hoy + dias, con los repetidos ya expandidos."""
    user, pwd = credenciales()
    client = caldav.DAVClient(url="https://caldav.icloud.com", username=user, password=pwd)
    desde = dt.datetime.combine(dt.datetime.now(TZ).date(), dt.time(), tzinfo=TZ)
    hasta = desde + dt.timedelta(days=dias)
    cals = {c.get_display_name(): c for c in client.principal().calendars()}
    eventos = []
    for nombre in CALENDARIOS:
        if nombre not in cals:
            continue
        for obj in cals[nombre].search(start=desde, end=hasta, event=True, expand=True):
            for comp in obj.icalendar_instance.walk("VEVENT"):
                ini, todo = a_local(comp.decoded("DTSTART"))
                fin = a_local(comp.decoded("DTEND"))[0] if "DTEND" in comp else None
                if todo and fin:
                    fin -= dt.timedelta(days=1)  # en iCalendar el fin de un evento de todo el día es exclusivo
                eventos.append({
                    "titulo": str(comp.get("SUMMARY", "(sin título)")),
                    "fecha": ini.date().isoformat(),
                    "fechaFin": fin.date().isoformat() if fin else ini.date().isoformat(),
                    "inicio": "" if todo else ini.strftime("%H:%M"),
                    "fin": "" if todo or not fin else fin.strftime("%H:%M"),
                    "calendario": nombre,
                })
    eventos.sort(key=lambda e: (e["fecha"], e["inicio"], e["titulo"]))
    return eventos


def crear_cita(titulo, fecha, inicio="", fin="", calendario=None, ubicacion=""):
    nombre = calendario or DEFECTO
    if nombre not in CALENDARIOS:
        raise ValueError(f"calendario no permitido: {nombre!r}")
    user, pwd = credenciales()
    client = caldav.DAVClient(url="https://caldav.icloud.com", username=user, password=pwd)
    cal = next((c for c in client.principal().calendars() if c.get_display_name() == nombre), None)
    if cal is None:
        raise ValueError(f"no existe el calendario {nombre!r} en iCloud")
    dia = dt.date.fromisoformat(fecha)
    campos = {"summary": titulo}
    if ubicacion:
        campos["location"] = ubicacion
    if inicio:
        ini = dt.datetime.combine(dia, dt.time.fromisoformat(inicio), tzinfo=TZ)
        end = dt.datetime.combine(dia, dt.time.fromisoformat(fin), tzinfo=TZ) if fin else ini + dt.timedelta(hours=1)
        if end <= ini:
            raise ValueError("la hora de fin debe ser posterior a la de inicio")
        cal.save_event(dtstart=ini, dtend=end, **campos)
    else:
        cal.save_event(dtstart=dia, dtend=dia + dt.timedelta(days=1), **campos)
    return {"calendario": nombre, "titulo": titulo, "fecha": fecha, "inicio": inicio, "fin": fin}


class Handler(BaseHTTPRequestHandler):
    def _json(self, codigo, cuerpo):
        datos = json.dumps(cuerpo, ensure_ascii=False).encode("utf8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/health":
            self._json(200, {"ok": True})
        elif url.path == "/proximos":
            try:
                dias = int(parse_qs(url.query).get("dias", ["7"])[0])
                if not 1 <= dias <= 60:
                    raise ValueError("dias debe estar entre 1 y 60")
                self._json(200, {"eventos": proximos(dias)})
            except ValueError as e:
                self._json(400, {"error": str(e)})
            except Exception as e:  # noqa: BLE001 — devolver un motivo genérico al cliente
                print(f"error: {e!r}", flush=True)
                self._json(500, {"error": "fallo al leer el calendario, ver el log del contenedor"})
        elif url.path == "/calendarios":
            self._json(200, {"calendarios": CALENDARIOS, "defecto": DEFECTO})
        else:
            self._json(404, {"error": "no existe"})

    def do_POST(self):
        if self.path != "/cita":
            return self._json(404, {"error": "no existe"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            d = json.loads(self.rfile.read(n) or b"{}")
            self._json(200, crear_cita(d["titulo"], d["fecha"], d.get("inicio", ""), d.get("fin", ""),
                                       d.get("calendario"), d.get("ubicacion", "")))
        except (KeyError, ValueError) as e:
            self._json(400, {"error": str(e)})
        except Exception as e:  # noqa: BLE001 — devolver un motivo genérico al cliente
            print(f"error: {e!r}", flush=True)
            self._json(500, {"error": "fallo al crear la cita, ver el log del contenedor"})

    def log_message(self, fmt, *args):
        print("http", fmt % args, flush=True)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "cita" and len(sys.argv) >= 4:
        a = sys.argv[2:]
        print(crear_cita(a[0], a[1], a[2] if len(a) > 2 else "", a[3] if len(a) > 3 else "", a[4] if len(a) > 4 else None))
    elif cmd == "proximos":
        print(json.dumps(proximos(int(sys.argv[2]) if len(sys.argv) > 2 else 7), ensure_ascii=False, indent=1))
    elif cmd == "run":
        ThreadingHTTPServer(("0.0.0.0", PUERTO), Handler).serve_forever()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
