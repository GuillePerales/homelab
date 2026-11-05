#!/usr/bin/env python3
"""Métricas diarias de Garmin Connect (API personal) a SQLite, servidas por HTTP al panel de Salud.

  salud.py sync [días]          descarga los últimos días (por defecto 3)
  salud.py backfill <días>      descarga el histórico hacia atrás, por bloques
  salud.py dia AAAA-MM-DD       muestra el registro guardado de un día
  salud.py remapear             rehace los registros desde las respuestas originales guardadas
  salud.py crudo AAAA-MM-DD     vuelca lo que devuelve Garmin para un día (depurar)
  salud.py run                  servidor HTTP + sincronización a las SYNC_HORAS (modo contenedor)

HTTP: GET /health · GET /estado · GET /dias?desde=AAAA-MM-DD&hasta=AAAA-MM-DD

Autenticación: la clave personal (GARMIN_API_KEY, connect.garmin.com → Personal API) se
canjea por un token de 24 h. La clave caduca (máximo un año): si la sincronización falla,
avisa por NTFY_URL y el panel muestra la fecha del último dato.
"""
import datetime as dt
import json
import os
import sqlite3
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.environ.get("TZ", "Europe/Madrid"))
DATOS = Path(os.environ.get("DATOS", "datos"))
DB = DATOS / "salud.db"
PUERTO = int(os.environ.get("PUERTO", "8080"))
HORAS = sorted({int(h) for h in os.environ.get("SYNC_HORAS", "7,13,22").split(",") if h.strip()})
NTFY = os.environ.get("NTFY_URL", "")
API = "https://personal.connectapi.garmin.com"
TOKEN_URL = f"{API}/personalapitoken-service/personal-api/personal-api-key/token"
BLOQUE = 28  # días por petición de rango
PAUSA = 1.0  # segundos entre llamadas

_token = {"valor": None, "caduca": 0.0}
_lock = threading.Lock()


# ── Base de datos ─────────────────────────────────────────────────────────────

def db():
    DATOS.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS dias (fecha TEXT PRIMARY KEY, datos TEXT NOT NULL, actualizado TEXT NOT NULL)")
    con.execute("CREATE TABLE IF NOT EXISTS estado (clave TEXT PRIMARY KEY, valor TEXT)")
    if "crudo" not in [c[1] for c in con.execute("PRAGMA table_info(dias)")]:
        con.execute("ALTER TABLE dias ADD COLUMN crudo TEXT")  # respuesta original de Garmin del día
    return con


def guardar(pares):
    """pares: (registro, respuesta original de Garmin de ese día). Se guarda también lo original
    para poder sacar métricas nuevas sin volver a descargar (salud.py remapear)."""
    with db() as con:
        con.executemany("INSERT OR REPLACE INTO dias (fecha, datos, actualizado, crudo) VALUES (?, ?, ?, ?)",
                        [(r["fecha"], json.dumps(r, ensure_ascii=False), ahora(), json.dumps(c, ensure_ascii=False))
                         for r, c in pares])


def remapear():
    """Rehace los registros a partir de las respuestas originales guardadas (tras cambiar registros())."""
    with db() as con:
        filas = con.execute("SELECT fecha, crudo FROM dias WHERE crudo IS NOT NULL").fetchall()
    pares = []
    for fecha, crudo_dia in filas:
        c = json.loads(crudo_dia)
        pares += registros(fecha, fecha, {"resumen": {"data": [c["resumen"]]}, "sueno": [c["sueno"]],
                                          "hrv": {"hrvSummaries": [c["hrv"]]}, "actividades": c["actividades"]})
    guardar(pares)
    print(f"remapeados {len(pares)} días", flush=True)


def dias(desde, hasta):
    with db() as con:
        filas = con.execute("SELECT datos FROM dias WHERE fecha BETWEEN ? AND ? ORDER BY fecha", (desde, hasta))
        return [json.loads(f[0]) for f in filas]


def poner_estado(clave, valor):
    with db() as con:
        con.execute("INSERT OR REPLACE INTO estado VALUES (?, ?)", (clave, valor))


def leer_estado():
    with db() as con:
        e = dict(con.execute("SELECT clave, valor FROM estado"))
        e["ultimo_dia"] = con.execute("SELECT max(fecha) FROM dias").fetchone()[0]
        e["dias_guardados"] = con.execute("SELECT count(*) FROM dias").fetchone()[0]
    return e


def ahora():
    return dt.datetime.now(TZ).isoformat(timespec="seconds")


# ── API personal de Garmin ────────────────────────────────────────────────────

def token():
    """Bearer de 24 h a partir de la clave; se renueva 10 min antes de caducar."""
    if _token["valor"] and time.time() < _token["caduca"] - 600:
        return _token["valor"]
    req = Request(TOKEN_URL, method="POST", data=b"",
                  headers={"Authorization": f"ApiKey {os.environ['GARMIN_API_KEY']}", "Accept": "*/*"})
    with urlopen(req, timeout=30) as r:
        cuerpo = r.read().decode()
    try:
        d = json.loads(cuerpo)
        valor = d.get("access_token") or d.get("accessToken") or d.get("token")
    except json.JSONDecodeError:
        valor = cuerpo.strip()  # por si devuelve el JWT en texto plano
    _token.update(valor=valor, caduca=time.time() + 23 * 3600)
    return valor


def get(ruta, **params):
    """GET a la API; None si ese recurso no tiene datos (404/204)."""
    time.sleep(PAUSA)
    url = f"{API}{ruta}" + (f"?{urlencode(params)}" if params else "")
    for intento in range(2):
        req = Request(url, headers={"Authorization": f"Bearer {token()}", "Accept": "application/json"})
        try:
            with urlopen(req, timeout=60) as r:
                cuerpo = r.read()
                return json.loads(cuerpo) if cuerpo else None
        except HTTPError as e:
            if e.code == 401 and intento == 0:
                _token["valor"] = None  # token revocado o caducado: canjear la clave otra vez
                continue
            if e.code in (204, 404):
                return None
            raise RuntimeError(f"{e.code} en {ruta}: {e.read()[:200]!r}") from None
    return None


def crudo(desde, hasta):
    """Respuestas de Garmin para un rango (AAAA-MM-DD, ambos incluidos; el sueño admite 31 días como máximo).
    El resumen diario (v2) ya trae pasos, calorías, FC, estrés, Body Battery, respiración y SpO2."""
    return {
        "resumen": get("/usersummary-service/v2/dailysummaries", startDate=desde, endDate=hasta),
        "sueno": get("/sleep-service/sleep/dailySleepSummariesByDate", startDate=desde, endDate=hasta),
        "hrv": get(f"/hrv-service/hrv/daily/{desde}/{hasta}"),
        "actividades": get("/activitylist-service/activities/search/activities",
                           start=0, limit=100, startDate=desde, endDate=hasta),
    }


# ── De la respuesta de Garmin a un registro por día ───────────────────────────
# Campos según la especificación OpenAPI de la API personal (developer.garmin.com → swagger-docs).

def g(d, *ruta):
    """Valor anidado o None si falta algún paso."""
    for k in ruta:
        d = d.get(k) if isinstance(d, dict) else None
    return d


def minutos(seg):
    return round(seg / 60) if isinstance(seg, (int, float)) else None


def hora(ms):
    """Los *TimestampLocal del sueño son milisegundos con la hora local tal cual: AAAA-MM-DDTHH:MM."""
    if not isinstance(ms, (int, float)):
        return None
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M")


def nonneg(v):
    return v if isinstance(v, (int, float)) and v >= 0 else None  # Garmin usa -1/-2 para "sin datos"


def registros(desde, hasta, c):
    """Por cada día del rango con datos: (registro con los nombres propios del panel, respuesta original del día)."""
    resumen = {r.get("calendarDate"): r for r in g(c, "resumen", "data") or []}
    sueno = {s.get("calendarDate"): s for s in c.get("sueno") or []}
    hrv = {h.get("calendarDate"): h for h in g(c, "hrv", "hrvSummaries") or []}
    acts = {}
    for a in c.get("actividades") or []:
        acts.setdefault((a.get("startTimeLocal") or "")[:10], []).append(a)

    out, d = [], dt.date.fromisoformat(desde)
    while d <= dt.date.fromisoformat(hasta):
        f = d.isoformat()
        r, s, h, a = resumen.get(f) or {}, sueno.get(f) or {}, hrv.get(f) or {}, sorted(
            acts.get(f, []), key=lambda x: x.get("startTimeLocal") or "")
        d += dt.timedelta(days=1)
        pasos = g(r, "movement", "steps") or {}
        if not (pasos.get("value") or s.get("sleepTimeSeconds") or a):
            continue  # el reloj no ha subido nada de ese día
        vo2 = [x["vO2MaxValue"] for x in a if x.get("vO2MaxValue")]
        out.append(({
            "fecha": f,
            "sueno": {
                "total_min": minutos(s.get("sleepTimeSeconds")),
                "profundo_min": minutos(s.get("deepSleepSeconds")),
                "ligero_min": minutos(s.get("lightSleepSeconds")),
                "rem_min": minutos(s.get("remSleepSeconds")),
                "despierto_min": minutos(s.get("awakeSleepSeconds")),
                "puntuacion": g(s, "sleepScores", "overall", "value"),
                "calidad": g(s, "sleepScores", "overall", "qualifierKey"),
                "inicio": hora(s.get("sleepStartTimestampLocal")),
                "fin": hora(s.get("sleepEndTimestampLocal")),
                "fc_media": s.get("avgHeartRate"),
                "estres": s.get("avgSleepStress"),
            },
            "fc": {"reposo": g(r, "heartRate", "restingValue"), "min": g(r, "heartRate", "minValue"),
                   "max": g(r, "heartRate", "maxValue")},
            "hrv": {"noche": h.get("lastNightAvg"), "semana": h.get("weeklyAvg"), "estado": h.get("status")},
            "estres": {"medio": nonneg(g(r, "stress", "avgLevel")), "max": nonneg(g(r, "stress", "maxLevel")),
                       "nivel": g(r, "stress", "qualifier")},
            "body_battery": {"max": g(r, "bodyBattery", "maxValue"), "min": g(r, "bodyBattery", "minValue"),
                             "cargado": g(r, "bodyBattery", "chargedValue"),
                             "gastado": g(r, "bodyBattery", "drainedValue")},
            "spo2": {"medio": g(r, "pulseOx", "avgValue") or s.get("averageSpO2Value"),
                     "min": g(r, "pulseOx", "minValue") or s.get("lowestSpO2Value")},
            "respiracion": g(r, "respiration", "avgValue") or s.get("averageRespirationValue"),
            "actividad": {
                "pasos": pasos.get("value"),
                "km": round(pasos["distanceInMeters"] / 1000, 2) if pasos.get("distanceInMeters") else None,
                "kcal_activas": g(r, "calories", "burnedActive"),
                "kcal_total": g(r, "calories", "burnedTotal"),
                "min_intensidad": ((g(r, "intensityMinutes", "moderate") or 0)
                                   + 2 * (g(r, "intensityMinutes", "vigorous") or 0)) or None,
                "pisos": g(r, "movement", "floorsAscended", "value"),
            },
            "vo2max": vo2[-1] if vo2 else None,
            "actividades": [{
                "nombre": x.get("activityName"),
                "tipo": g(x, "activityType", "typeKey"),
                "km": round((x.get("distance") or 0) / 1000, 2),
                "min": minutos(x.get("duration")),
                "fc_media": x.get("averageHR"),
                "kcal": x.get("calories"),
                "inicio": x.get("startTimeLocal"),
                "efecto": x.get("trainingEffectLabel"),
            } for x in a],
        }, {"resumen": r, "sueno": s, "hrv": h, "actividades": a}))
    return out


# ── Sincronización ────────────────────────────────────────────────────────────

def bloques(desde, hasta):
    d = desde
    while d <= hasta:
        h = min(d + dt.timedelta(days=BLOQUE - 1), hasta)
        yield d, h
        d = h + dt.timedelta(days=1)


def descargar(desde, hasta):
    for d, h in bloques(desde, hasta):
        guardar(registros(d.isoformat(), h.isoformat(), crudo(d.isoformat(), h.isoformat())))
        print(f"guardado {d} → {h}", flush=True)


def sync(n_dias=3, revisar=False):
    """Descarga los últimos n_dias (hoy incluido): Garmin completa datos con retraso.
    Con revisar, avisa si el reloj lleva más de 3 días sin subir datos (una vez al día)."""
    with _lock:
        try:
            hoy = dt.datetime.now(TZ).date()
            descargar(hoy - dt.timedelta(days=n_dias - 1), hoy)
            poner_estado("ultima_sync", ahora())
            poner_estado("ultimo_error", "")
            ultimo = leer_estado()["ultimo_dia"]
            if revisar and ultimo and (hoy - dt.date.fromisoformat(ultimo)).days > 3:
                avisar(f"El reloj no sube datos a Garmin Connect desde el {ultimo}: sincronízalo desde la app.")
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"[:300]
            poner_estado("ultimo_error", f"{ahora()} {msg}")
            print(f"error en sync: {msg}", flush=True)
            avisar(f"La sincronización con Garmin ha fallado: {msg}")


def avisar(texto):
    if not NTFY:
        return
    try:
        urlopen(Request(NTFY, data=texto.encode(), headers={"Title": "salud: Garmin", "Tags": "warning"}), timeout=10)
    except Exception as e:  # noqa: BLE001
        print(f"no se pudo avisar por ntfy: {e!r}", flush=True)


def programador():
    """Sincroniza al arrancar y luego a cada hora de SYNC_HORAS."""
    sync()
    while True:
        t = dt.datetime.now(TZ)
        hoy = [t.replace(hour=h, minute=5, second=0, microsecond=0) for h in HORAS]
        prox = min(s for s in hoy + [s + dt.timedelta(days=1) for s in hoy] if s > t)
        time.sleep((prox - t).total_seconds())
        sync(revisar=prox.hour == HORAS[0])


# ── HTTP ──────────────────────────────────────────────────────────────────────

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
        q = parse_qs(url.query)
        if url.path == "/health":
            self._json(200, {"ok": True})
        elif url.path == "/estado":
            self._json(200, leer_estado())
        elif url.path == "/dias":
            try:
                hoy = dt.datetime.now(TZ).date()
                hasta = dt.date.fromisoformat(q.get("hasta", [hoy.isoformat()])[0])
                desde = dt.date.fromisoformat(q.get("desde", [(hasta - dt.timedelta(days=62)).isoformat()])[0])
                if not 0 <= (hasta - desde).days <= 800:
                    raise ValueError("rango de fechas no válido (máximo 800 días)")
                self._json(200, {"dias": dias(desde.isoformat(), hasta.isoformat()), "estado": leer_estado()})
            except ValueError as e:
                self._json(400, {"error": str(e)})
        else:
            self._json(404, {"error": "no existe"})

    def log_message(self, fmt, *args):
        print("http", fmt % args, flush=True)


def main():
    cmd, a = (sys.argv[1] if len(sys.argv) > 1 else ""), sys.argv[2:]
    hoy = dt.datetime.now(TZ).date()
    if cmd == "sync":
        sync(int(a[0]) if a else 3)
        print(json.dumps(leer_estado(), ensure_ascii=False))
    elif cmd == "backfill" and a:
        descargar(hoy - dt.timedelta(days=int(a[0]) - 1), hoy)
    elif cmd == "remapear":
        remapear()
    elif cmd == "dia" and a:
        print(json.dumps(dias(a[0], a[0]), ensure_ascii=False, indent=1))
    elif cmd == "crudo" and a:
        print(json.dumps(crudo(a[0], a[1] if len(a) > 1 else a[0]), ensure_ascii=False, indent=1))
    elif cmd == "run":
        threading.Thread(target=programador, daemon=True).start()
        ThreadingHTTPServer(("0.0.0.0", PUERTO), Handler).serve_forever()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
