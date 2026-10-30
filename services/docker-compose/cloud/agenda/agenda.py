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
import base64
import datetime as dt
import json
import os
import re
import sys
import uuid
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.environ.get("TZ", "Europe/Madrid"))
CALENDARIOS = [c.strip() for c in os.environ.get("CALENDARIOS", "Eventos").split(",") if c.strip()]
DEFECTO = os.environ.get("CALENDARIO_DEFECTO", CALENDARIOS[0])
PUERTO = int(os.environ.get("PUERTO", "8080"))
RAIZ = "https://caldav.icloud.com/"
D, C = "{DAV:}", "{urn:ietf:params:xml:ns:caldav}"
NS = 'xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"'
_calendarios = {}  # nombre -> URL, se descubre una vez por proceso


def credenciales():
    user, pwd = os.environ.get("ICLOUD_USER"), os.environ.get("ICLOUD_PASS")
    if not (user and pwd):
        user, pwd = [l.strip() for l in (Path.home() / ".icloud-caldav").read_text(encoding="utf8").splitlines()[:2]]
    return user, pwd


def dav(metodo, url, cuerpo=None, profundidad=None, extra=None):
    """Petición CalDAV con auth básica. Devuelve (estado, texto)."""
    user, pwd = credenciales()
    cab = {"Authorization": "Basic " + base64.b64encode(f"{user}:{pwd}".encode()).decode(),
           "Content-Type": "application/xml; charset=utf-8"}
    if profundidad is not None:
        cab["Depth"] = str(profundidad)
    cab.update(extra or {})
    req = Request(url, data=cuerpo.encode("utf8") if cuerpo else None, headers=cab, method=metodo)
    with urlopen(req, timeout=30) as r:
        return r.status, r.read().decode("utf8")


def propfind(url, props, profundidad):
    cuerpo = f'<D:propfind {NS}><D:prop>{props}</D:prop></D:propfind>'
    return ET.fromstring(dav("PROPFIND", url, cuerpo, profundidad)[1])


def descubrir():
    """Rellena _calendarios: principal -> calendar-home-set -> calendarios con su nombre."""
    raiz = propfind(RAIZ, "<D:current-user-principal/>", 0)
    principal = urljoin(RAIZ, raiz.find(f".//{D}current-user-principal/{D}href").text)
    home = propfind(principal, "<C:calendar-home-set/>", 0)
    home = urljoin(principal, home.find(f".//{C}calendar-home-set/{D}href").text)
    for r in propfind(home, "<D:displayname/><D:resourcetype/>", 1).findall(f"{D}response"):
        if r.find(f".//{D}resourcetype/{C}calendar") is not None:
            nombre = r.find(f".//{D}displayname")
            if nombre is not None and nombre.text:
                _calendarios[nombre.text] = urljoin(home, r.find(f"{D}href").text)


def url_calendario(nombre):
    if nombre not in _calendarios:
        descubrir()
    if nombre not in _calendarios:
        raise ValueError(f"no existe el calendario {nombre!r} en iCloud")
    return _calendarios[nombre]


def valor_ical(params, valor):
    """Devuelve (datetime local, todo_el_dia) para un DTSTART/DTEND de iCalendar."""
    if "VALUE=DATE" in params or re.fullmatch(r"\d{8}", valor):
        return dt.datetime.combine(dt.datetime.strptime(valor, "%Y%m%d").date(), dt.time(), tzinfo=TZ), True
    t = dt.datetime.strptime(valor.rstrip("Z"), "%Y%m%dT%H%M%S")
    if valor.endswith("Z"):
        return t.replace(tzinfo=dt.timezone.utc).astimezone(TZ), False
    tzid = re.search(r"TZID=([^;:]+)", params)
    try:
        zona = ZoneInfo(tzid.group(1)) if tzid else TZ
    except Exception:  # noqa: BLE001 — zona desconocida: tratarla como local
        zona = TZ
    return t.replace(tzinfo=zona).astimezone(TZ), False


def eventos_ical(texto):
    """Extrae (SUMMARY, DTSTART, DTEND) de cada VEVENT; ignora los VALARM anidados."""
    lineas = re.sub(r"\r?\n[ \t]", "", texto).splitlines()
    actual, alarma = None, False
    for l in lineas:
        if l == "BEGIN:VEVENT":
            actual = {}
        elif l == "END:VEVENT":
            if actual and "DTSTART" in actual:
                yield actual
            actual = None
        elif actual is not None and l == "BEGIN:VALARM":
            alarma = True
        elif l == "END:VALARM":
            alarma = False
        elif actual is not None and not alarma and ":" in l:
            cabecera, valor = l.split(":", 1)
            nombre, _, params = cabecera.partition(";")
            actual.setdefault(nombre.upper(), (params, valor))


def desescapar(t):
    return re.sub(r"\\(.)", lambda m: "\n" if m.group(1) in "nN" else m.group(1), t)


def escapar(t):
    return t.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def proximos(dias):
    """Eventos desde hoy hasta hoy + dias, con los repetidos ya expandidos por el servidor."""
    desde = dt.datetime.combine(dt.datetime.now(TZ).date(), dt.time(), tzinfo=TZ)
    hasta = desde + dt.timedelta(days=dias)
    f = "%Y%m%dT%H%M%SZ"
    rango = f'start="{desde.astimezone(dt.timezone.utc).strftime(f)}" end="{hasta.astimezone(dt.timezone.utc).strftime(f)}"'
    cuerpo = (f'<C:calendar-query {NS}><D:prop><C:calendar-data><C:expand {rango}/></C:calendar-data></D:prop>'
              f'<C:filter><C:comp-filter name="VCALENDAR"><C:comp-filter name="VEVENT">'
              f'<C:time-range {rango}/></C:comp-filter></C:comp-filter></C:filter></C:calendar-query>')
    eventos = []
    for nombre in CALENDARIOS:
        try:
            url = url_calendario(nombre)
        except ValueError:
            continue
        for dato in ET.fromstring(dav("REPORT", url, cuerpo, 1)[1]).iter(f"{C}calendar-data"):
            for ev in eventos_ical(dato.text or ""):
                ini, todo = valor_ical(*ev["DTSTART"])
                fin = valor_ical(*ev["DTEND"])[0] if "DTEND" in ev else None
                if todo and fin:
                    fin -= dt.timedelta(days=1)  # en iCalendar el fin de un evento de todo el día es exclusivo
                eventos.append({
                    "titulo": desescapar(ev["SUMMARY"][1]) if "SUMMARY" in ev else "(sin título)",
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
    url = url_calendario(nombre)
    dia = dt.date.fromisoformat(fecha)
    if inicio:
        ini = dt.datetime.combine(dia, dt.time.fromisoformat(inicio), tzinfo=TZ)
        end = dt.datetime.combine(dia, dt.time.fromisoformat(fin), tzinfo=TZ) if fin else ini + dt.timedelta(hours=1)
        if end <= ini:
            raise ValueError("la hora de fin debe ser posterior a la de inicio")
        f = "%Y%m%dT%H%M%SZ"
        fechas = [f"DTSTART:{ini.astimezone(dt.timezone.utc).strftime(f)}", f"DTEND:{end.astimezone(dt.timezone.utc).strftime(f)}"]
    else:
        fechas = [f"DTSTART;VALUE=DATE:{dia:%Y%m%d}", f"DTEND;VALUE=DATE:{dia + dt.timedelta(days=1):%Y%m%d}"]
    uid = str(uuid.uuid4())
    lineas = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//homelab agenda//ES", "BEGIN:VEVENT", f"UID:{uid}",
              f"DTSTAMP:{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%SZ}", *fechas, f"SUMMARY:{escapar(titulo)}"]
    if ubicacion:
        lineas.append(f"LOCATION:{escapar(ubicacion)}")
    lineas += ["END:VEVENT", "END:VCALENDAR"]
    dav("PUT", urljoin(url, f"{uid}.ics"), "\r\n".join(lineas) + "\r\n",
        extra={"Content-Type": "text/calendar; charset=utf-8", "If-None-Match": "*"})
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
