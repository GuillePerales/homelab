#!/usr/bin/env python3
"""Métricas de Garmin Connect (API personal) a SQLite, servidas por HTTP al panel de Salud.

  salud.py sync [días]          descarga los últimos días (por defecto 3)
  salud.py backfill <días>      descarga el histórico hacia atrás, por bloques
  salud.py dia AAAA-MM-DD       muestra el registro guardado de un día
  salud.py remapear             rehace los registros desde las respuestas originales guardadas
  salud.py refit                vuelve a procesar los FIT guardados (tras cambiar procesar_fit())
  salud.py crudo AAAA-MM-DD     vuelca lo que devuelve Garmin para un día (depurar)
  salud.py run                  servidor HTTP + sincronización a las SYNC_HORAS (modo contenedor)

HTTP: GET /health · GET /estado
      GET /dias?desde=AAAA-MM-DD&hasta=AAAA-MM-DD   un registro por día + zonas de FC
      GET /fc?fecha=AAAA-MM-DD                      FC del día cada 2 min ([minuto del día, ppm])
      GET /actividad?id=N                           detalle, vueltas, series y recorrido del FIT

Qué guarda: por día el resumen (pasos, calorías, FC, estrés, Body Battery, SpO2, respiración),
el sueño, la HRV, el peso y la composición corporal, la FC intradía y las actividades; por
actividad el detalle de Garmin y su FIT (ZIP original en $DATOS/fit y lo procesado en SQLite).

Autenticación: la clave personal (GARMIN_API_KEY, connect.garmin.com → Personal API) se
canjea por un token de 24 h. La clave caduca (máximo un año): si la sincronización falla,
avisa por NTFY_URL y el panel muestra la fecha del último dato.
"""
import datetime as dt
import io
import json
import math
import os
import sqlite3
import sys
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.environ.get("TZ", "Europe/Madrid"))
DATOS = Path(os.environ.get("DATOS", "datos"))
DB = DATOS / "salud.db"
FIT = DATOS / "fit"
PUERTO = int(os.environ.get("PUERTO", "8080"))
HORAS = sorted({int(h) for h in os.environ.get("SYNC_HORAS", "7,13,22").split(",") if h.strip()})
NTFY = os.environ.get("NTFY_URL", "")
API = "https://personal.connectapi.garmin.com"
TOKEN_URL = f"{API}/personalapitoken-service/personal-api/personal-api-key/token"
BLOQUE = 28  # días por petición de rango
PAUSA = 1.0  # segundos entre llamadas
MAX_SERIE = 1500  # puntos como máximo de las series de una actividad
MAX_RUTA = 800  # puntos como máximo del recorrido
PIE = ("running", "walking", "hiking", "trail_running", "treadmill_running", "indoor_running")

_token = {"valor": None, "caduca": 0.0}
_lock = threading.Lock()


# ── Base de datos ─────────────────────────────────────────────────────────────

def db():
    DATOS.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS dias (fecha TEXT PRIMARY KEY, datos TEXT NOT NULL, actualizado TEXT NOT NULL)")
    con.execute("CREATE TABLE IF NOT EXISTS estado (clave TEXT PRIMARY KEY, valor TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS fc_dia (fecha TEXT PRIMARY KEY, valores TEXT NOT NULL)")
    con.execute("CREATE TABLE IF NOT EXISTS actividades (id INTEGER PRIMARY KEY, fecha TEXT, lista TEXT, "
                "detalle TEXT, fit TEXT, actualizado TEXT)")
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
        pares += registros(fecha, fecha, {
            "resumen": {"data": [c["resumen"]]}, "sueno": [c["sueno"]], "hrv": {"hrvSummaries": [c["hrv"]]},
            "actividades": c["actividades"], "peso": {"dailyWeightSummaries": [c["peso"]] if c.get("peso") else []}})
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
        e["actividades_guardadas"] = con.execute("SELECT count(*) FROM actividades WHERE fit IS NOT NULL").fetchone()[0]
    e.pop("zonas", None)  # va aparte en /dias
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


def pedir(ruta, accept="application/json", **params):
    """Bytes de un GET a la API; None si ese recurso no tiene datos (404/204)."""
    time.sleep(PAUSA)
    url = f"{API}{ruta}" + (f"?{urlencode(params)}" if params else "")
    for intento in range(2):
        req = Request(url, headers={"Authorization": f"Bearer {token()}", "Accept": accept})
        try:
            with urlopen(req, timeout=120) as r:
                return r.read() or None
        except HTTPError as e:
            if e.code == 401 and intento == 0:
                _token["valor"] = None  # token revocado o caducado: canjear la clave otra vez
                continue
            if e.code in (204, 404):
                return None
            raise RuntimeError(f"{e.code} en {ruta}: {e.read()[:200]!r}") from None
    return None


def get(ruta, **params):
    cuerpo = pedir(ruta, **params)
    return json.loads(cuerpo) if cuerpo else None


def crudo(desde, hasta):
    """Respuestas de Garmin para un rango (AAAA-MM-DD, ambos incluidos; el sueño admite 31 días como máximo).
    El resumen diario (v2) ya trae pasos, calorías, FC, estrés, Body Battery, respiración y SpO2."""
    return {
        "resumen": get("/usersummary-service/v2/dailysummaries", startDate=desde, endDate=hasta),
        "sueno": get("/sleep-service/sleep/dailySleepSummariesByDate", startDate=desde, endDate=hasta),
        "hrv": get(f"/hrv-service/hrv/daily/{desde}/{hasta}"),
        "actividades": get("/activitylist-service/activities/search/activities",
                           start=0, limit=100, startDate=desde, endDate=hasta),
        "peso": get(f"/weight-service/weight/range/{desde}/{hasta}", includeAll="true"),
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


def redondear(v, n=1):
    return round(v, n) if isinstance(v, (int, float)) else None


def gramos(v, n=1):
    return round(v / 1000, n) if isinstance(v, (int, float)) else None


def hora(ms):
    """Los *TimestampLocal del sueño son milisegundos con la hora local tal cual: AAAA-MM-DDTHH:MM."""
    if not isinstance(ms, (int, float)):
        return None
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M")


def nonneg(v):
    return v if isinstance(v, (int, float)) and v >= 0 else None  # Garmin usa -1/-2 para "sin datos"


def actividad_breve(x):
    """Lo que el panel enseña de una actividad en la lista del día (sale de la lista de Garmin)."""
    zonas = [x.get(f"hrTimeInZone_{i}") for i in range(1, 6)]
    return {
        "id": x.get("activityId"),
        "nombre": x.get("activityName"),
        "tipo": g(x, "activityType", "typeKey"),
        "km": round((x.get("distance") or 0) / 1000, 2),
        "min": minutos(x.get("duration")),
        "fc_media": x.get("averageHR"),
        "fc_max": x.get("maxHR"),
        "kcal": x.get("calories"),
        "inicio": x.get("startTimeLocal"),
        "efecto": x.get("trainingEffectLabel"),
        "efecto_aerobico": x.get("aerobicTrainingEffect"),
        "efecto_anaerobico": x.get("anaerobicTrainingEffect"),
        "carga": redondear(x.get("activityTrainingLoad")),
        "zonas_min": [round(z / 60, 1) for z in zonas] if any(zonas) else None,
        "vo2max": x.get("vO2MaxValue"),
    }


def peso_dia(p):
    """Último pesaje del día. Grasa y agua en %, masas en kg. Sin báscula conectada solo llega el peso."""
    w = (p or {}).get("latestWeight") or {}
    if not w.get("weight"):
        return None
    return {
        "kg": gramos(w.get("weight")), "imc": redondear(w.get("bmi")), "grasa_pct": redondear(w.get("bodyFat")),
        "agua_pct": redondear(w.get("bodyWater")), "musculo_kg": gramos(w.get("muscleMass")),
        "hueso_kg": gramos(w.get("boneMass")), "visceral": w.get("visceralFat"),
        "edad_metabolica": w.get("metabolicAge"), "fuente": w.get("sourceType"),
    }


def registros(desde, hasta, c):
    """Por cada día del rango con datos: (registro con los nombres propios del panel, respuesta original del día)."""
    resumen = {r.get("calendarDate"): r for r in g(c, "resumen", "data") or []}
    sueno = {s.get("calendarDate"): s for s in c.get("sueno") or []}
    hrv = {h.get("calendarDate"): h for h in g(c, "hrv", "hrvSummaries") or []}
    pesos = {p.get("summaryDate"): p for p in g(c, "peso", "dailyWeightSummaries") or []}
    acts = {}
    for a in c.get("actividades") or []:
        acts.setdefault((a.get("startTimeLocal") or "")[:10], []).append(a)

    out, d = [], dt.date.fromisoformat(desde)
    while d <= dt.date.fromisoformat(hasta):
        f = d.isoformat()
        r, s, h, p = resumen.get(f) or {}, sueno.get(f) or {}, hrv.get(f) or {}, pesos.get(f)
        a = sorted(acts.get(f, []), key=lambda x: x.get("startTimeLocal") or "")
        d += dt.timedelta(days=1)
        pasos = g(r, "movement", "steps") or {}
        if not (pasos.get("value") or s.get("sleepTimeSeconds") or a or peso_dia(p)):
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
            "peso": peso_dia(p),
            "vo2max": vo2[-1] if vo2 else None,
            "actividades": [actividad_breve(x) for x in a],
        }, {"resumen": r, "sueno": s, "hrv": h, "actividades": a, "peso": p}))
    return out


# ── FC intradía ───────────────────────────────────────────────────────────────

def guardar_fc(fecha):
    """FC del día cada 2 min como [minuto del día, ppm] (los timestamps de Garmin van en UTC)."""
    r = get("/wellness-service/wellness/dailyHeartRate", date=fecha) or {}
    vals = []
    for ts, fc in r.get("heartRateValues") or []:
        if fc:
            local = dt.datetime.fromtimestamp(ts / 1000, TZ)
            vals.append([(local.date() - dt.date.fromisoformat(fecha)).days * 1440 + local.hour * 60 + local.minute, fc])
    if vals:
        with db() as con:
            con.execute("INSERT OR REPLACE INTO fc_dia VALUES (?, ?)", (fecha, json.dumps(vals)))


def fc_de(fecha):
    with db() as con:
        f = con.execute("SELECT valores FROM fc_dia WHERE fecha = ?", (fecha,)).fetchone()
    return json.loads(f[0]) if f else []


# ── Actividades: detalle de Garmin y FIT ──────────────────────────────────────

FIT_EPOCH = 631065600  # 1989-12-31T00:00:00Z, origen de los timestamps FIT
SEMI = 180 / 2 ** 31  # semicírculos FIT → grados


def procesar_fit(zip_bytes):
    """Del ZIP con el FIT: resumen de la sesión, vueltas, series (submuestreadas) y recorrido."""
    from garmin_fit_sdk import Decoder, Stream  # solo hace falta al procesar FIT
    z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    nombre = next(n for n in z.namelist() if n.lower().endswith(".fit"))
    msgs, errores = Decoder(Stream.from_byte_array(bytearray(z.read(nombre)))).read(convert_datetimes_to_dates=False)
    ses = (msgs.get("session_mesgs") or [{}])[0]
    deporte = ses.get("sport")
    pie = str(deporte) in ("running", "walking", "hiking") or str(ses.get("sub_sport")) in PIE
    cad = lambda m, base, frac: (None if m.get(base) is None else
                                 round((m[base] + (m.get(frac) or 0)) * (2 if pie else 1)))  # pasos/min a pie

    vueltas = []
    for i, l in enumerate(msgs.get("lap_mesgs") or []):
        dist, tiempo = l.get("total_distance") or 0, l.get("total_timer_time") or 0
        vueltas.append({
            "n": i + 1, "km": round(dist / 1000, 3), "seg": round(tiempo),
            "ritmo_s_km": round(tiempo / (dist / 1000)) if dist > 50 else None,
            "fc_media": l.get("avg_heart_rate"), "fc_max": l.get("max_heart_rate"),
            "cadencia": cad(l, "avg_running_cadence" if l.get("avg_running_cadence") is not None else "avg_cadence",
                            "avg_fractional_cadence"),
            "subida": l.get("total_ascent"), "bajada": l.get("total_descent"),
            "potencia": l.get("avg_power"), "zancada_m": redondear((l.get("avg_step_length") or 0) / 1000, 2) or None,
        })

    recs = [r for r in msgs.get("record_mesgs") or [] if r.get("timestamp")]
    t0 = recs[0]["timestamp"] if recs else 0
    paso = max(1, math.ceil(len(recs) / MAX_SERIE))
    series = {"t": [], "km": [], "fc": [], "ritmo_s_km": [], "cadencia": [], "altitud": [], "potencia": []}
    for r in recs[::paso]:
        v = r.get("enhanced_speed") if r.get("enhanced_speed") is not None else r.get("speed")
        series["t"].append(r["timestamp"] - t0)
        series["km"].append(redondear((r.get("distance") or 0) / 1000, 3))
        series["fc"].append(r.get("heart_rate"))
        series["ritmo_s_km"].append(round(1000 / v) if v and v > 0.5 else None)
        series["cadencia"].append(cad(r, "cadence", "fractional_cadence"))
        alt = r.get("enhanced_altitude") if r.get("enhanced_altitude") is not None else r.get("altitude")
        series["altitud"].append(redondear(alt))
        series["potencia"].append(r.get("power"))
    series = {k: v for k, v in series.items() if any(x is not None for x in v)}  # fuera las que el reloj no mide

    # Recorrido como [lat, lon, FC] (FC None si el punto no la trae) para colorearlo por zona en el panel.
    gps = [(r["position_lat"] * SEMI, r["position_long"] * SEMI, r.get("heart_rate")) for r in recs
           if r.get("position_lat") is not None and r.get("position_long") is not None]
    ruta = [[round(a, 6), round(b, 6), fc] for a, b, fc in gps[::max(1, math.ceil(len(gps) / MAX_RUTA))]]

    sesion = {
        "deporte": str(deporte) if deporte is not None else None, "subdeporte": str(ses.get("sub_sport") or ""),
        "inicio_utc": dt.datetime.fromtimestamp(FIT_EPOCH + ses["start_time"], dt.timezone.utc).isoformat()
        if ses.get("start_time") else None,
        "km": redondear((ses.get("total_distance") or 0) / 1000, 2), "seg": redondear(ses.get("total_timer_time"), 0),
        "seg_total": redondear(ses.get("total_elapsed_time"), 0),
        "fc_media": ses.get("avg_heart_rate"), "fc_max": ses.get("max_heart_rate"),
        "subida": ses.get("total_ascent"), "bajada": ses.get("total_descent"),
        "cadencia": cad(ses, "avg_running_cadence" if ses.get("avg_running_cadence") is not None else "avg_cadence",
                        "avg_fractional_cadence"),
        "potencia": ses.get("avg_power"), "potencia_normalizada": ses.get("normalized_power"),
        "efecto_aerobico": ses.get("total_training_effect"),
        "efecto_anaerobico": ses.get("total_anaerobic_training_effect"),
        "oscilacion_mm": redondear(ses.get("avg_vertical_oscillation")),
        "contacto_ms": redondear(ses.get("avg_stance_time")),
        "zancada_m": redondear((ses.get("avg_step_length") or 0) / 1000, 2) or None,
        "ratio_vertical": redondear(ses.get("avg_vertical_ratio")),
        "kcal": ses.get("total_calories"),
    }
    return {"sesion": sesion, "vueltas": vueltas, "series": series, "ruta": ruta,
            "intervalo_s": paso, "errores_fit": [str(e) for e in errores][:3]}


def detalle_breve(d):
    """Del detalle de Garmin: los campos escalares del resumen con valor y los tramos por tipo."""
    s = {k: v for k, v in (g(d, "summaryDTO") or {}).items() if isinstance(v, (int, float, str)) and v not in (0, "", None)}
    tramos = [{"tipo": x.get("splitType"), "veces": x.get("noOfSplits"), "km": redondear((x.get("distance") or 0) / 1000, 2),
               "seg": redondear(x.get("duration"), 0), "fc_media": x.get("averageHR")}
              for x in g(d, "splitSummaries") or []]
    return {"resumen": s, "tramos": tramos, "lugar": d.get("locationName") if d else None}


def guardar_actividades(lista, forzar=False):
    """Guarda la lista y, para las que aún no lo tienen, el detalle y el FIT (una vez por actividad)."""
    FIT.mkdir(parents=True, exist_ok=True)
    for a in lista or []:
        aid = a.get("activityId")
        if not aid:
            continue
        with db() as con:
            tiene = con.execute("SELECT fit IS NOT NULL FROM actividades WHERE id = ?", (aid,)).fetchone()
            con.execute("INSERT INTO actividades (id, fecha, lista, actualizado) VALUES (?, ?, ?, ?) "
                        "ON CONFLICT(id) DO UPDATE SET lista = excluded.lista, actualizado = excluded.actualizado",
                        (aid, (a.get("startTimeLocal") or "")[:10], json.dumps(a, ensure_ascii=False), ahora()))
        if tiene and tiene[0] and not forzar:
            continue
        detalle = get(f"/activity-service/activity/{aid}")
        z = pedir(f"/download-service/files/activity/{aid}", accept="*/*")
        fit = None
        if z:
            (FIT / f"{aid}.zip").write_bytes(z)
            try:
                fit = procesar_fit(z)
            except Exception as e:  # noqa: BLE001 — un FIT raro no tumba la sincronización
                print(f"aviso: FIT de {aid}: {e!r}", flush=True)
                fit = {"error": str(e)[:200]}
        with db() as con:
            con.execute("UPDATE actividades SET detalle = ?, fit = ?, actualizado = ? WHERE id = ?",
                        (json.dumps(detalle, ensure_ascii=False), json.dumps(fit, ensure_ascii=False), ahora(), aid))
        print(f"actividad {aid} {a.get('activityName')}", flush=True)


def refit():
    """Vuelve a procesar los ZIP de FIT guardados, sin descargar."""
    n = 0
    for z in sorted(FIT.glob("*.zip")):
        try:
            fit = procesar_fit(z.read_bytes())
        except Exception as e:  # noqa: BLE001
            fit = {"error": str(e)[:200]}
        with db() as con:
            con.execute("UPDATE actividades SET fit = ? WHERE id = ?", (json.dumps(fit, ensure_ascii=False), int(z.stem)))
        n += 1
    print(f"reprocesados {n} FIT", flush=True)


def actividad(aid):
    with db() as con:
        f = con.execute("SELECT lista, detalle, fit FROM actividades WHERE id = ?", (aid,)).fetchone()
    if not f:
        return None
    lista = json.loads(f[0]) if f[0] else {}
    return {"actividad": actividad_breve(lista), "detalle": detalle_breve(json.loads(f[1]) if f[1] else None),
            "fit": json.loads(f[2]) if f[2] else None}


# ── Sincronización ────────────────────────────────────────────────────────────

def bloques(desde, hasta):
    d = desde
    while d <= hasta:
        h = min(d + dt.timedelta(days=BLOQUE - 1), hasta)
        yield d, h
        d = h + dt.timedelta(days=1)


def descargar(desde, hasta):
    for d, h in bloques(desde, hasta):
        c = crudo(d.isoformat(), h.isoformat())
        regs = registros(d.isoformat(), h.isoformat(), c)
        guardar(regs)
        for r, _ in regs:
            guardar_fc(r["fecha"])
        guardar_actividades(c.get("actividades"))
        print(f"guardado {d} → {h}", flush=True)
    zonas = get("/biometric-service/heartRateZones/v2")
    if zonas:
        poner_estado("zonas", json.dumps(zonas))


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
        try:
            if url.path == "/health":
                self._json(200, {"ok": True})
            elif url.path == "/estado":
                self._json(200, leer_estado())
            elif url.path == "/dias":
                hoy = dt.datetime.now(TZ).date()
                hasta = dt.date.fromisoformat(q.get("hasta", [hoy.isoformat()])[0])
                desde = dt.date.fromisoformat(q.get("desde", [(hasta - dt.timedelta(days=62)).isoformat()])[0])
                if not 0 <= (hasta - desde).days <= 800:
                    raise ValueError("rango de fechas no válido (máximo 800 días)")
                with db() as con:
                    z = con.execute("SELECT valor FROM estado WHERE clave = 'zonas'").fetchone()
                self._json(200, {"dias": dias(desde.isoformat(), hasta.isoformat()), "estado": leer_estado(),
                                 "zonas": json.loads(z[0]) if z else None})
            elif url.path == "/fc":
                fecha = dt.date.fromisoformat(q["fecha"][0]).isoformat()
                self._json(200, {"fecha": fecha, "valores": fc_de(fecha)})
            elif url.path == "/actividad":
                a = actividad(int(q["id"][0]))
                self._json(200 if a else 404, a or {"error": "no existe esa actividad"})
            else:
                self._json(404, {"error": "no existe"})
        except (KeyError, ValueError) as e:
            self._json(400, {"error": f"parámetro no válido: {e}"})

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
    elif cmd == "refit":
        refit()
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
