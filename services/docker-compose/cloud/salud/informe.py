"""Señales por reglas, resumen mensual e informe en PDF a partir de los registros diarios de salud.py.

Todo compara con la línea base propia (media de los 28 días anteriores a la ventana), no con
valores genéricos. Las metas de META son las de objetivos-salud.js del vault: si cambia una
allí, cambiarla aquí. Las señales describen patrones de los datos, no diagnostican nada.

  senales(dias, hasta)       lista de señales evaluadas en la fecha `hasta` (ventana de 7 días)
  resumen_mes(dias, mes)     cifras del mes frente al anterior, semanas, actividades y señales
  pdf(dias, mes)             informe del mes en PDF (bytes); necesita matplotlib

`dias` es la lista de registros de salud.dias(): basta con que cubra desde 35 días antes del
primer día evaluado.
"""
import datetime as dt
import io
import statistics as st
import textwrap

META = {"sueno": 450, "punt": 80, "pasos": 7000, "kcal": 2400, "fuerza": 3, "fuerza_min": 30, "correr": 3}
BASE = 28  # días de la línea base
VENTANA = 7
NIVELES = {"alerta": 0, "aviso": 1, "info": 2, "bien": 3}
RUN = ("running", "trail_running", "treadmill_running", "indoor_running", "track_running")
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
         "octubre", "noviembre", "diciembre"]


# ── Utilidades ────────────────────────────────────────────────────────────────

def _f(s):
    return dt.date.fromisoformat(s)


def _media(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return st.fmean(xs) if xs else None


def _sd(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return st.stdev(xs) if len(xs) > 1 else None


def _num(xs):
    return [x for x in xs if isinstance(x, (int, float))]


def _g(d, *ruta):
    for k in ruta:
        d = d.get(k) if isinstance(d, dict) else None
    return d


def llevado(d):
    """El reloj se llevó ese día (no es un día con cuatro datos sueltos)."""
    return (_g(d, "actividad", "pasos") or 0) >= 1000 or bool(_g(d, "sueno", "total_min"))


def es_run(t):
    return (t or "") in RUN or "running" in (t or "")


def es_fuerza(a):
    return "strength" in (a.get("tipo") or "") and (a.get("min") or 0) >= META["fuerza_min"]


def hm(m):
    if m is None:
        return "—"
    m = round(m)
    return f"{m // 60}h{m % 60:02d}"


def rango(dias, hasta, n, desplazar=0):
    """Registros de los n días que acaban en `hasta` - desplazar (incluido)."""
    fin = hasta - dt.timedelta(days=desplazar)
    ini = fin - dt.timedelta(days=n - 1)
    return [d for d in dias if ini <= _f(d["fecha"]) <= fin]


def carga_dia(d):
    return sum(a.get("carga") or 0 for a in d.get("actividades") or [])


def _s(nivel, area, titulo, detalle):
    return {"nivel": nivel, "area": area, "titulo": titulo, "detalle": detalle}


# ── Señales ───────────────────────────────────────────────────────────────────

def senales(dias, hasta):
    """Señales de los 7 días que acaban en `hasta` frente a los 28 anteriores."""
    hasta = _f(hasta) if isinstance(hasta, str) else hasta
    v = [d for d in rango(dias, hasta, VENTANA) if llevado(d)]
    b = [d for d in rango(dias, hasta, BASE, desplazar=VENTANA) if llevado(d)]
    noches_v = [d for d in v if _g(d, "sueno", "total_min")]
    noches_b = [d for d in b if _g(d, "sueno", "total_min")]
    out = []

    faltan = VENTANA - len(v)
    if faltan >= 2:
        out.append(_s("info", "Datos", "Días sin datos completos",
                      f"{faltan} de los últimos 7 días sin llevar el reloj o sin sincronizar: las señales son menos fiables."))
    if len(v) < 3:
        return out

    # Recuperación: HRV y FC en reposo nocturnas frente a la línea base
    hv, hb = _num(_g(d, "hrv", "noche") for d in noches_v), _num(_g(d, "hrv", "noche") for d in noches_b)
    fv, fb = _num(_g(d, "fc", "reposo") for d in noches_v), _num(_g(d, "fc", "reposo") for d in noches_b)
    rv, rb = _num(d.get("respiracion") for d in noches_v), _num(d.get("respiracion") for d in noches_b)
    dh = df = None
    if len(hv) >= 3 and len(hb) >= 10:
        dh = (_media(hv) - _media(hb)) / _media(hb)
    if len(fv) >= 3 and len(fb) >= 10:
        df = _media(fv) - _media(fb)
    txt_h = f"HRV {_media(hv):.0f} ms frente a tu media de {_media(hb):.0f} ({dh:+.0%})" if dh is not None else ""
    txt_f = f"FC en reposo {_media(fv):.0f} ppm frente a {_media(fb):.0f} ({df:+.0f})" if df is not None else ""
    if dh is not None and df is not None and dh <= -0.10 and df >= 3:
        out.append(_s("alerta", "Recuperación", "Recuperación baja",
                      f"{txt_h} y {txt_f}. Juntas suelen acompañar a fatiga acumulada, poco sueño, estrés o el inicio "
                      "de un catarro: conviene bajar la intensidad unos días y priorizar el descanso."))
    elif dh is not None and dh <= -0.10:
        out.append(_s("aviso", "Recuperación", "HRV por debajo de lo habitual",
                      f"{txt_h}. Si sigue así varios días, es señal de que el cuerpo no termina de recuperarse."))
    elif df is not None and df >= 3:
        out.append(_s("aviso", "Recuperación", "FC en reposo más alta",
                      f"{txt_f}. Puede venir de cansancio, alcohol, calor, cenas tardías o de empezar a ponerse malo."))
    elif dh is not None and df is not None and dh >= -0.03 and df <= 1:
        out.append(_s("bien", "Recuperación", "Buena recuperación", f"{txt_h}; {txt_f}."))
    estados = [_g(d, "hrv", "estado") for d in noches_v[-3:]]
    if len(estados) == 3 and all(e in ("LOW", "POOR", "UNBALANCED") for e in estados):
        out.append(_s("aviso", "Recuperación", "Estado de HRV de Garmin fuera de rango",
                      "Las tres últimas noches Garmin marca la HRV como desequilibrada o baja."))
    if len(rv) >= 3 and len(rb) >= 10 and df is not None and _media(rv) - _media(rb) >= 1 and df >= 3:
        out.append(_s("aviso", "Recuperación", "Respiración y pulso nocturnos al alza",
                      f"Respiración {_media(rv):.1f} rpm frente a {_media(rb):.1f} y la FC en reposo también sube. "
                      "Es un patrón que a veces precede a un resfriado o aparece con fiebre; si te encuentras mal, descansa."))

    # Sueño
    t = _num(_g(d, "sueno", "total_min") for d in noches_v)
    if len(t) >= 4:
        m, cortas = _media(t), sum(1 for x in t if x < 420)
        deuda = sum(max(0, META["sueno"] - x) for x in t)
        if m < 390:
            out.append(_s("alerta", "Sueño", "Sueño insuficiente",
                          f"Media de {hm(m)} en las últimas {len(t)} noches ({cortas} por debajo de 7 h); "
                          f"faltan {hm(deuda)} acumuladas frente a la meta de {hm(META['sueno'])}."))
        elif m < META["sueno"] and cortas >= 3:
            out.append(_s("aviso", "Sueño", "Noches cortas",
                          f"{cortas} de {len(t)} noches por debajo de 7 h (media {hm(m)}, meta {hm(META['sueno'])})."))
        elif m >= META["sueno"]:
            out.append(_s("bien", "Sueño", "Duración de sueño en meta", f"Media de {hm(m)} en {len(t)} noches."))
        p = _num(_g(d, "sueno", "puntuacion") for d in noches_v)
        if len(p) >= 4 and _media(p) < 70:
            out.append(_s("aviso", "Sueño", "Sueño de poca calidad",
                          f"Puntuación media de {_media(p):.0f} (meta: más de {META['punt']})."))
        ini = []
        for d in noches_v:
            h = _g(d, "sueno", "inicio")
            if h:
                x = int(h[11:13]) * 60 + int(h[14:16])
                ini.append(x + 1440 if x < 720 else x)  # pasada la medianoche cuenta como el mismo día
        if len(ini) >= 4 and _sd(ini) > 60:
            out.append(_s("aviso", "Sueño", "Horario de sueño irregular",
                          f"La hora de dormirse varía {round(_sd(ini))} min de media entre noches "
                          f"(de {hm(min(ini) % 1440)} a {hm(max(ini) % 1440)}). Un horario estable suele mejorar el sueño."))

    # Energía y estrés
    bb = _num(_g(d, "body_battery", "max") for d in v)
    if len(bb) >= 4 and _media(bb) < 60:
        out.append(_s("aviso", "Energía", "Body Battery que no se recarga",
                      f"El máximo diario medio es {_media(bb):.0f}: la noche no llega a recargar la batería."))
    ev, eb = _num(_g(d, "estres", "medio") for d in v), _num(_g(d, "estres", "medio") for d in b)
    if len(ev) >= 4 and len(eb) >= 10 and _media(ev) - _media(eb) >= 8:
        out.append(_s("aviso", "Energía", "Estrés más alto de lo habitual",
                      f"Estrés medio de {_media(ev):.0f} frente a tu media de {_media(eb):.0f}."))

    # Entrenamiento: carga aguda (7 días) frente a crónica (28 días, por semana)
    aguda = sum(carga_dia(d) for d in rango(dias, hasta, VENTANA))
    cronica = sum(carga_dia(d) for d in rango(dias, hasta, BASE)) / 4
    acts = [a for d in rango(dias, hasta, VENTANA) for a in d.get("actividades") or []]
    if not acts:
        out.append(_s("aviso", "Entrenamiento", "Sin entrenamientos en 7 días",
                      "No hay ninguna actividad registrada en la última semana."))
    elif cronica >= 50:
        r = aguda / cronica
        txt = f"Carga de la semana {aguda:.0f} frente a {cronica:.0f} de media semanal en las últimas 4 (ratio {r:.2f}).".replace(f"{r:.2f}", f"{r:.2f}".replace(".", ","))
        if r > 1.5:
            out.append(_s("alerta", "Entrenamiento", "Subida brusca de carga",
                          f"{txt} Subir más de un 50 % de golpe es cuando más lesiones aparecen: mejor progresar poco a poco."))
        elif r > 1.3:
            out.append(_s("aviso", "Entrenamiento", "Carga al alza", f"{txt} Vigila la recuperación esta semana."))
        elif r < 0.6:
            out.append(_s("aviso", "Entrenamiento", "Carga a la baja",
                          f"{txt} Bien si es una semana de descarga; si no, el plan se está quedando corto."))
        else:
            out.append(_s("bien", "Entrenamiento", "Carga equilibrada", txt))
    fuerza = len({d["fecha"] for d in rango(dias, hasta, VENTANA) for a in d.get("actividades") or [] if es_fuerza(a)})
    correr = len({d["fecha"] for d in rango(dias, hasta, VENTANA) for a in d.get("actividades") or [] if es_run(a.get("tipo"))})
    if acts and (fuerza < META["fuerza"] or correr < META["correr"]):
        out.append(_s("aviso", "Entrenamiento", "Plan de la semana incompleto",
                      f"Fuerza {fuerza}/{META['fuerza']} días y correr {correr}/{META['correr']} días en los últimos 7."))
    elif acts:
        out.append(_s("bien", "Entrenamiento", "Plan de la semana cumplido",
                      f"Fuerza {fuerza} días y correr {correr} días en los últimos 7."))

    # Actividad diaria
    pa = _num(_g(d, "actividad", "pasos") for d in v)
    if len(pa) >= 4:
        if _media(pa) < 0.8 * META["pasos"]:
            out.append(_s("aviso", "Actividad", "Poco movimiento diario",
                          f"Media de {_media(pa):,.0f} pasos (meta {META['pasos']:,}).".replace(",", ".")))
        elif _media(pa) >= META["pasos"]:
            out.append(_s("bien", "Actividad", "Pasos en meta", f"Media de {_media(pa):,.0f} pasos.".replace(",", ".")))

    # Cuerpo
    pesos = [(d["fecha"], _g(d, "peso", "kg")) for d in rango(dias, hasta, BASE) if _g(d, "peso", "kg")]
    if len(pesos) >= 2 and abs(pesos[-1][1] - pesos[0][1]) >= 1.5:
        dif = pesos[-1][1] - pesos[0][1]
        out.append(_s("aviso", "Cuerpo", "Cambio de peso rápido",
                      f"{dif:+.1f} kg entre el {pesos[0][0]} y el {pesos[-1][0]}."))
    sp = _num(_g(d, "spo2", "medio") for d in noches_v)
    if len(sp) >= 3 and _media(sp) < 93:
        out.append(_s("aviso", "Cuerpo", "SpO2 nocturna baja",
                      f"Media de {_media(sp):.0f} %. La medida de muñeca es ruidosa; si se repite o hay ronquidos o "
                      "cansancio al despertar, merece comentarlo con un médico."))

    return sorted(out, key=lambda s: NIVELES[s["nivel"]])


# ── Resumen del mes ───────────────────────────────────────────────────────────

def limites(mes):
    a, m = map(int, mes.split("-"))
    ini = dt.date(a, m, 1)
    fin = (ini + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(days=1)
    return ini, fin


def mes_anterior(mes):
    ini, _ = limites(mes)
    return (ini - dt.timedelta(days=1)).strftime("%Y-%m")


def nombre_mes(mes):
    ini, _ = limites(mes)
    return f"{MESES[ini.month - 1].capitalize()} {ini.year}"


METRICAS = [
    # clave, etiqueta, unidad, función sobre los días llevados, meta, más es mejor
    ("sueno", "Sueño por noche", "h", lambda ds: _media(_g(d, "sueno", "total_min") for d in ds), META["sueno"], True),
    ("punt", "Puntuación de sueño", "", lambda ds: _media(_g(d, "sueno", "puntuacion") for d in ds), META["punt"], True),
    ("hrv", "HRV nocturna", "ms", lambda ds: _media(_g(d, "hrv", "noche") for d in ds), None, True),
    ("fc", "FC en reposo", "ppm", lambda ds: _media(_g(d, "fc", "reposo") for d in ds if _g(d, "sueno", "total_min")), None, False),
    ("bb", "Body Battery máximo", "", lambda ds: _media(_g(d, "body_battery", "max") for d in ds), None, True),
    ("estres", "Estrés medio", "", lambda ds: _media(_g(d, "estres", "medio") for d in ds), None, False),
    ("pasos", "Pasos al día", "", lambda ds: _media(_g(d, "actividad", "pasos") for d in ds), META["pasos"], True),
    ("kcal", "Kcal quemadas al día", "", lambda ds: _media(_g(d, "actividad", "kcal_total") for d in ds), META["kcal"], True),
    ("intens", "Minutos de intensidad a la semana", "min",
     lambda ds: (sum(_g(d, "actividad", "min_intensidad") or 0 for d in ds) / len(ds) * 7) if ds else None, 150, True),
    ("km", "Km corridos", "km", lambda ds: sum(a.get("km") or 0 for d in ds for a in d.get("actividades") or []
                                               if es_run(a.get("tipo"))), None, True),
    ("sesiones", "Sesiones de entrenamiento", "", lambda ds: sum(len(d.get("actividades") or []) for d in ds), None, True),
    ("carga", "Carga de entrenamiento", "", lambda ds: sum(carga_dia(d) for d in ds), None, None),
    ("vo2", "VO2max (último)", "", lambda ds: next((d["vo2max"] for d in reversed(ds) if d.get("vo2max")), None), None, True),
    ("peso", "Peso (último)", "kg", lambda ds: next((_g(d, "peso", "kg") for d in reversed(ds) if _g(d, "peso", "kg")), None),
     None, None),
]


def _del_mes(dias, mes):
    ini, fin = limites(mes)
    return [d for d in dias if ini <= _f(d["fecha"]) <= fin]


def semanas_mes(dias, mes):
    """Semanas ISO que tocan el mes: fuerza, correr, km, sesiones y carga."""
    ini, fin = limites(mes)
    lunes = ini - dt.timedelta(days=ini.weekday())
    out = []
    while lunes <= fin:
        dom = lunes + dt.timedelta(days=6)
        ds = [d for d in dias if lunes <= _f(d["fecha"]) <= dom]
        acts = [(d["fecha"], a) for d in ds for a in d.get("actividades") or []]
        out.append({
            "lunes": lunes.isoformat(), "semana": lunes.strftime("%G-W%V"),
            "fuerza": len({f for f, a in acts if es_fuerza(a)}),
            "correr": len({f for f, a in acts if es_run(a.get("tipo"))}),
            "km": round(sum(a.get("km") or 0 for _, a in acts if es_run(a.get("tipo"))), 1),
            "sesiones": len(acts), "min": sum(a.get("min") or 0 for _, a in acts),
            "carga": round(sum(a.get("carga") or 0 for _, a in acts)),
        })
        lunes += dt.timedelta(days=7)
    return out


def resumen_mes(dias, mes):
    """Cifras del mes y del anterior, semanas, actividades y señales (al cierre y cada domingo)."""
    ini, fin = limites(mes)
    hoy = dt.date.today()
    corte = min(fin, hoy)
    ds = [d for d in _del_mes(dias, mes) if llevado(d)]
    ant = [d for d in _del_mes(dias, mes_anterior(mes)) if llevado(d)]
    metricas = []
    for k, etiqueta, u, fn, meta, mejor in METRICAS:
        metricas.append({"clave": k, "etiqueta": etiqueta, "unidad": u, "valor": fn(ds) if ds else None,
                         "anterior": fn(ant) if ant else None, "meta": meta, "mas_es_mejor": mejor})
    domingos, d = [], ini + dt.timedelta(days=(6 - ini.weekday()) % 7)
    while d <= corte:
        domingos.append(d)
        d += dt.timedelta(days=7)
    acts = [dict(a, fecha=x["fecha"]) for x in _del_mes(dias, mes) for a in x.get("actividades") or []]
    return {
        "mes": mes, "nombre": nombre_mes(mes), "desde": ini.isoformat(), "hasta": fin.isoformat(),
        "completo": hoy > fin, "dias_con_datos": len(ds), "dias_mes": (fin - ini).days + 1,
        "metricas": metricas, "semanas": semanas_mes(dias, mes), "actividades": acts,
        "senales_cierre": senales(dias, corte),
        "senales_semanas": [{"hasta": x.isoformat(), "senales": [s for s in senales(dias, x) if s["nivel"] in ("alerta", "aviso")]}
                            for x in domingos],
        "metas": META,
    }


# ── PDF ───────────────────────────────────────────────────────────────────────

TINTA, SUAVE, LINEA, FONDO = "#1f2328", "#656d76", "#d0d7de", "#f6f8fa"
AZUL, VERDE, NARANJA, ROJO, MORADO, GRIS = "#2f6fb0", "#2e8b57", "#d9822b", "#c93c37", "#7b5ea7", "#8c959f"
COLOR_NIVEL = {"alerta": ROJO, "aviso": NARANJA, "info": GRIS, "bien": VERDE}
EFECTO = {"UNKNOWN": "", "NO_BENEFIT": "sin beneficio", "RECOVERY": "recuperación", "AEROBIC_BASE": "base aeróbica",
          "TEMPO": "tempo", "LACTATE_THRESHOLD": "umbral", "VO2MAX": "VO2max", "SPEED": "velocidad",
          "ANAEROBIC_CAPACITY": "capacidad anaeróbica"}
ETIQUETA_NIVEL = {"alerta": "Alerta", "aviso": "Aviso", "info": "Info", "bien": "Bien"}


def _fmt(m, v):
    if v is None:
        return "—"
    if m["clave"] == "sueno":
        return hm(v)
    if m["clave"] in ("pasos", "kcal", "carga", "intens", "sesiones"):
        return f"{v:,.0f}".replace(",", ".")
    if m["clave"] in ("km", "peso", "vo2"):
        return f"{v:.1f}".replace(".", ",") + (f" {m['unidad']}" if m["unidad"] else "")
    return f"{v:.0f}" + (f" {m['unidad']}" if m["unidad"] else "")


def _dif(m):
    v, a = m["valor"], m["anterior"]
    if v is None or a is None or a == 0:
        return "—", SUAVE
    d = v - a
    if m["clave"] == "sueno":
        txt = f"{d:+.0f} min"
    elif m["clave"] in ("km", "peso", "vo2"):
        txt = f"{d:+.1f}".replace(".", ",")
    elif m["clave"] in ("pasos", "kcal", "carga", "intens"):
        txt = f"{d / a:+.0%}"
    else:
        txt = f"{d:+.0f}"
    if m["mas_es_mejor"] is None or abs(d) < 1e-9:
        return txt, SUAVE
    return txt, VERDE if (d > 0) == m["mas_es_mejor"] else ROJO


def _nan(vals):
    """None → NaN para que matplotlib corte la línea en los días sin datos en vez de unirlos."""
    return [v if isinstance(v, (int, float)) else float("nan") for v in vals]


def pdf(dias, mes):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 8, "axes.edgecolor": LINEA, "axes.labelcolor": SUAVE,
        "xtick.color": SUAVE, "ytick.color": SUAVE, "axes.spines.top": False, "axes.spines.right": False,
        "axes.titlesize": 9.5, "axes.titleweight": "bold", "axes.titlecolor": TINTA, "axes.titlelocation": "left",
        "axes.grid": True, "grid.color": "#eaeef2", "grid.linewidth": 0.6, "axes.axisbelow": True,
    })
    R = resumen_mes(dias, mes)
    ini, fin = limites(mes)
    ds = _del_mes(dias, mes)
    fechas = [dt.datetime.combine(_f(d["fecha"]), dt.time()) for d in ds]
    A4 = (8.27, 11.69)
    buf = io.BytesIO()

    def cabecera(fig, titulo, pagina):
        fig.text(0.07, 0.955, titulo, fontsize=15, fontweight="bold", color=TINTA)
        fig.text(0.07, 0.935, f"Informe de salud · {R['nombre']}", fontsize=8.5, color=SUAVE)
        fig.text(0.93, 0.955, str(pagina), fontsize=8.5, color=SUAVE, ha="right")
        fig.add_artist(plt.Line2D([0.07, 0.93], [0.925, 0.925], color=LINEA, lw=0.8))

    def eje_mes(ax):
        ax.set_xlim(dt.datetime.combine(ini, dt.time()) - dt.timedelta(hours=14),
                    dt.datetime.combine(fin, dt.time()) + dt.timedelta(hours=14))
        ax.xaxis.set_major_locator(mdates.DayLocator(bymonthday=[1, 8, 15, 22, 29]))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d"))

    def serie(fn, solo_llevado=True):
        return [fn(d) if (llevado(d) or not solo_llevado) else None for d in ds]

    def sin_datos(ax):
        ax.text(0.5, 0.5, "Sin datos este mes", transform=ax.transAxes, ha="center", va="center", color=SUAVE)

    with PdfPages(buf, metadata={"Title": f"Informe de salud {mes}", "Author": "salud (homelab)"}) as pp:
        # Página 1: resumen y señales
        fig = plt.figure(figsize=A4)
        cabecera(fig, "Resumen del mes", 1)
        estado = "mes completo" if R["completo"] else f"mes en curso, hasta el {min(fin, dt.date.today()).strftime('%d/%m')}"
        fig.text(0.07, 0.905, f"{R['dias_con_datos']} de {R['dias_mes']} días con datos ({estado}). "
                 f"Comparado con {nombre_mes(mes_anterior(mes)).lower()}.", fontsize=8.5, color=SUAVE)
        y = 0.875
        for x, t, ha in ((0.07, "Métrica", "left"), (0.55, "Este mes", "right"), (0.70, "Anterior", "right"),
                         (0.82, "Diferencia", "right"), (0.93, "Meta", "right")):
            fig.text(x, y, t, fontsize=7.5, color=SUAVE, ha=ha, fontweight="bold")
        y -= 0.008
        for i, m in enumerate(R["metricas"]):
            y -= 0.022
            if i % 2 == 0:
                fig.add_artist(plt.Rectangle((0.06, y - 0.006), 0.88, 0.022, color=FONDO, lw=0, zorder=-1))
            dif, col = _dif(m)
            meta = "—" if m["meta"] is None else (hm(m["meta"]) if m["clave"] == "sueno" else
                                                   (f"> {m['meta']}" if m["clave"] == "punt" else f"{m['meta']:,}".replace(",", ".")))
            ok = m["meta"] is not None and m["valor"] is not None and (
                m["valor"] > m["meta"] if m["clave"] == "punt" else m["valor"] >= m["meta"])
            fig.text(0.07, y, m["etiqueta"], fontsize=8.5, color=TINTA)
            fig.text(0.55, y, _fmt(m, m["valor"]), fontsize=8.5, color=VERDE if ok else TINTA, ha="right",
                     fontweight="bold")
            fig.text(0.70, y, _fmt(m, m["anterior"]), fontsize=8.5, color=SUAVE, ha="right")
            fig.text(0.82, y, dif, fontsize=8.5, color=col, ha="right")
            fig.text(0.93, y, meta, fontsize=8.5, color=SUAVE, ha="right")

        y -= 0.05
        fig.text(0.07, y, "Señales al cierre", fontsize=11, fontweight="bold", color=TINTA)
        y -= 0.012
        fig.text(0.07, y - 0.008, "Últimos 7 días frente a los 28 anteriores. Son patrones de los datos, no un diagnóstico.",
                 fontsize=7.5, color=SUAVE)
        y -= 0.02
        for s in R["senales_cierre"] or [_s("info", "Datos", "Sin señales", "No hay datos suficientes para evaluar.")]:
            if y < 0.12:
                break
            y -= 0.03
            fig.add_artist(plt.Circle((0.077, y + 0.004), 0.0045, color=COLOR_NIVEL[s["nivel"]],
                                      transform=fig.transFigure))
            fig.text(0.09, y, f"{s['titulo']}", fontsize=9, fontweight="bold", color=TINTA)
            fig.text(0.93, y, f"{s['area']} · {ETIQUETA_NIVEL[s['nivel']]}", fontsize=7.5,
                     color=COLOR_NIVEL[s["nivel"]], ha="right")
            for linea in textwrap.wrap(s["detalle"], 105):
                y -= 0.016
                fig.text(0.09, y, linea, fontsize=7.8, color=SUAVE)

        sem = [x for x in R["senales_semanas"] if x["senales"]]
        if sem and y > 0.16:
            y -= 0.045
            fig.text(0.07, y, "Avisos durante el mes", fontsize=11, fontweight="bold", color=TINTA)
            for x in sem:
                if y < 0.07:
                    break
                y -= 0.02
                f = _f(x["hasta"])
                fig.text(0.07, y, f"Semana al {f.strftime('%d/%m')}", fontsize=8, color=SUAVE)
                txt = " · ".join(s["titulo"] for s in x["senales"])
                fig.text(0.24, y, textwrap.shorten(txt, 110, placeholder="…"), fontsize=8, color=TINTA)
        pp.savefig(fig)
        plt.close(fig)

        # Página 2: sueño y recuperación
        fig, axs = plt.subplots(4, 1, figsize=A4, gridspec_kw={"hspace": 0.55, "top": 0.89, "bottom": 0.05,
                                                                "left": 0.09, "right": 0.95})
        cabecera(fig, "Sueño y recuperación", 2)
        ax = axs[0]
        prof = [(_g(d, "sueno", "profundo_min") or 0) / 60 for d in ds]
        rem = [(_g(d, "sueno", "rem_min") or 0) / 60 for d in ds]
        lig = [(_g(d, "sueno", "ligero_min") or 0) / 60 for d in ds]
        if any(prof) or any(lig):
            ax.bar(fechas, prof, color="#1f4e79", width=0.75, label="Profundo")
            ax.bar(fechas, rem, bottom=prof, color=MORADO, width=0.75, label="REM")
            ax.bar(fechas, lig, bottom=[a + b for a, b in zip(prof, rem)], color="#9cc3e6", width=0.75, label="Ligero")
            ax.axhline(META["sueno"] / 60, color=VERDE, lw=1, ls="--", label=f"Meta {hm(META['sueno'])}")
            ax.legend(loc="upper left", ncol=4, fontsize=7, frameon=False, bbox_to_anchor=(0, 1.02))
            ax.set_ylim(0, 10.5)
        else:
            sin_datos(ax)
        ax.set_title("Duración y fases del sueño (h)", pad=14)
        eje_mes(ax)

        ax = axs[1]
        p = serie(lambda d: _g(d, "sueno", "puntuacion"))
        cols = [VERDE if v and v > META["punt"] else NARANJA if v and v >= 60 else ROJO for v in p]
        pts = [(f, v, c) for f, v, c in zip(fechas, p, cols) if v]
        if pts:
            ax.scatter([x[0] for x in pts], [x[1] for x in pts], c=[x[2] for x in pts], s=18, zorder=3)
            ax.plot(fechas, _nan(p), color=LINEA, lw=0.8)
            ax.axhline(META["punt"], color=VERDE, lw=1, ls="--")
            ax.set_ylim(min(40, min(x[1] for x in pts) - 5), 100)
        else:
            sin_datos(ax)
        ax.set_title("Puntuación de sueño")
        eje_mes(ax)

        ax = axs[2]
        h = serie(lambda d: _g(d, "hrv", "noche"))
        base = []
        for d in ds:  # banda de la línea base móvil: media ± desviación de los 28 días anteriores
            prev = _num(_g(x, "hrv", "noche") for x in rango(dias, _f(d["fecha"]), BASE, desplazar=1))
            base.append((_media(prev), _sd(prev)) if len(prev) >= 10 else (None, None))
        if any(h):
            bf = [(f, m, s) for f, (m, s) in zip(fechas, base) if m is not None and s is not None]
            if bf:
                ax.fill_between([x[0] for x in bf], [x[1] - x[2] for x in bf], [x[1] + x[2] for x in bf],
                                color=AZUL, alpha=0.12, lw=0, label="Tu rango habitual")
                ax.plot([x[0] for x in bf], [x[1] for x in bf], color=AZUL, lw=0.8, alpha=0.5)
            ax.plot(fechas, _nan(h), color=AZUL, lw=1.6, marker="o", ms=3, label="HRV")
            ax.legend(loc="upper left", fontsize=7, frameon=False, ncol=2, bbox_to_anchor=(0, 1.02))
        else:
            sin_datos(ax)
        ax.set_title("HRV nocturna (ms)", pad=14)
        eje_mes(ax)

        ax = axs[3]
        fc = serie(lambda d: _g(d, "fc", "reposo") if _g(d, "sueno", "total_min") else None)
        fp = [(f, v) for f, v in zip(fechas, fc) if v]
        if fp:
            ax.plot(fechas, _nan(fc), color=ROJO, lw=1.6, marker="o", ms=3)
            prev = _num(_g(x, "fc", "reposo") for x in rango(dias, ini, BASE, desplazar=1) if _g(x, "sueno", "total_min"))
            if len(prev) >= 10:
                ax.axhline(_media(prev), color=GRIS, lw=1, ls="--", label="Media de los 28 días previos al mes")
                ax.legend(loc="upper left", fontsize=7, frameon=False, bbox_to_anchor=(0, 1.02))
        else:
            sin_datos(ax)
        ax.set_title("FC en reposo (ppm)", pad=14)
        eje_mes(ax)
        pp.savefig(fig)
        plt.close(fig)

        # Página 3: actividad y energía
        fig, axs = plt.subplots(4, 1, figsize=A4, gridspec_kw={"hspace": 0.55, "top": 0.89, "bottom": 0.05,
                                                                "left": 0.09, "right": 0.95})
        cabecera(fig, "Actividad y energía", 3)
        ax = axs[0]
        pa = serie(lambda d: _g(d, "actividad", "pasos"))
        if any(pa):
            ax.bar(fechas, [v or 0 for v in pa], width=0.75,
                   color=[VERDE if (v or 0) >= META["pasos"] else "#9cc3e6" for v in pa])
            ax.axhline(META["pasos"], color=VERDE, lw=1, ls="--")
            ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v / 1000:.0f}k"))
        else:
            sin_datos(ax)
        ax.set_title(f"Pasos (meta {META['pasos']:,})".replace(",", "."))
        eje_mes(ax)

        ax = axs[1]
        cg = [carga_dia(d) for d in ds]
        if any(cg):
            ax.bar(fechas, cg, width=0.75, color=NARANJA, label="Carga del día")
            ratio = []
            for d in ds:
                f = _f(d["fecha"])
                ag = sum(carga_dia(x) for x in rango(dias, f, VENTANA))
                cr = sum(carga_dia(x) for x in rango(dias, f, BASE)) / 4
                ratio.append(ag / cr if cr >= 50 else None)
            ax2 = ax.twinx()
            rp = [(f, r) for f, r in zip(fechas, ratio) if r is not None]
            if rp:
                ax2.axhspan(0.8, 1.3, color=VERDE, alpha=0.08, lw=0)
                ax2.plot([x[0] for x in rp], [x[1] for x in rp], color=TINTA, lw=1.2, label="Aguda / crónica")
                ax2.set_ylim(0, max(2, max(x[1] for x in rp) + 0.2))
            ax2.grid(False)
            ax2.spines["right"].set_visible(True)
            ax2.set_ylabel("Ratio aguda/crónica", fontsize=7)
            h1, l1 = ax.get_legend_handles_labels()
            h2, l2 = ax2.get_legend_handles_labels()
            ax.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=7, frameon=False, ncol=2, bbox_to_anchor=(0, 1.02))
        else:
            sin_datos(ax)
        ax.set_title("Carga de entrenamiento (franja verde del ratio: 0,8–1,3)", pad=14)
        eje_mes(ax)

        ax = axs[2]
        bmax = serie(lambda d: _g(d, "body_battery", "max"))
        bmin = serie(lambda d: _g(d, "body_battery", "min"))
        bp = [(f, a, b) for f, a, b in zip(fechas, bmax, bmin) if a is not None and b is not None]
        if bp:
            ax.bar([x[0] for x in bp], [x[1] - x[2] for x in bp], bottom=[x[2] for x in bp], width=0.6,
                   color=[VERDE if x[1] >= 80 else NARANJA if x[1] >= 60 else ROJO for x in bp], alpha=0.85)
            ax.set_ylim(0, 100)
        else:
            sin_datos(ax)
        ax.set_title("Body Battery: del mínimo al máximo de cada día")
        eje_mes(ax)

        ax = axs[3]
        es = serie(lambda d: _g(d, "estres", "medio"))
        ep = [(f, v) for f, v in zip(fechas, es) if v is not None]
        if ep:
            ax.plot(fechas, _nan(es), color=MORADO, lw=1.6, marker="o", ms=3)
            ax.axhspan(0, 25, color=VERDE, alpha=0.07, lw=0)
            ax.axhspan(50, 100, color=ROJO, alpha=0.05, lw=0)
            ax.set_ylim(0, max(60, max(x[1] for x in ep) + 5))
        else:
            sin_datos(ax)
        ax.set_title("Estrés medio del día (0–25 reposo, 50+ alto)")
        eje_mes(ax)
        pp.savefig(fig)
        plt.close(fig)

        # Página 4: entrenamiento
        fig = plt.figure(figsize=A4)
        cabecera(fig, "Entrenamiento", 4)
        y = 0.895
        fig.text(0.07, y, f"Por semana (meta: fuerza {META['fuerza']} días de {META['fuerza_min']} min o más "
                 f"y correr {META['correr']} días)", fontsize=10, fontweight="bold", color=TINTA)
        y -= 0.025
        cab = (("Semana", 0.07, "left"), ("Fuerza", 0.30, "right"), ("Correr", 0.42, "right"), ("Km", 0.54, "right"),
               ("Sesiones", 0.67, "right"), ("Minutos", 0.80, "right"), ("Carga", 0.93, "right"))
        for t, x, ha in cab:
            fig.text(x, y, t, fontsize=7.5, color=SUAVE, ha=ha, fontweight="bold")
        for i, s in enumerate(R["semanas"]):
            y -= 0.02
            if i % 2 == 0:
                fig.add_artist(plt.Rectangle((0.06, y - 0.005), 0.88, 0.02, color=FONDO, lw=0, zorder=-1))
            lun = _f(s["lunes"])
            vals = (f"{lun.strftime('%d/%m')} – {(lun + dt.timedelta(days=6)).strftime('%d/%m')}",
                    f"{s['fuerza']}/{META['fuerza']}", f"{s['correr']}/{META['correr']}",
                    f"{s['km']:.1f}".replace(".", ","), str(s["sesiones"]), str(s["min"]), str(s["carga"]))
            for (t, x, ha), v in zip(cab, vals):
                ok = (t == "Fuerza" and s["fuerza"] >= META["fuerza"]) or (t == "Correr" and s["correr"] >= META["correr"])
                fig.text(x, y, v, fontsize=8.3, ha=ha, color=VERDE if ok else TINTA, fontweight="bold" if ok else "normal")

        y -= 0.05
        fig.text(0.07, y, "Actividades del mes", fontsize=10, fontweight="bold", color=TINTA)
        y -= 0.025
        cab = (("Fecha", 0.07, "left"), ("Actividad", 0.17, "left"), ("Km", 0.56, "right"), ("Min", 0.63, "right"),
               ("FC media", 0.72, "right"), ("Carga", 0.80, "right"), ("Efecto", 0.82, "left"))
        for t, x, ha in cab:
            fig.text(x, y, t, fontsize=7.5, color=SUAVE, ha=ha, fontweight="bold")
        acts = R["actividades"]
        if not acts:
            fig.text(0.07, y - 0.025, "Ninguna actividad registrada este mes.", fontsize=8.5, color=SUAVE)
        for i, a in enumerate(acts):
            y -= 0.0185
            if y < 0.05:
                fig.text(0.07, y, f"… y {len(acts) - i} más", fontsize=8, color=SUAVE)
                break
            if i % 2 == 0:
                fig.add_artist(plt.Rectangle((0.06, y - 0.005), 0.88, 0.0185, color=FONDO, lw=0, zorder=-1))
            vals = (_f(a["fecha"]).strftime("%d/%m"), textwrap.shorten(a.get("nombre") or a.get("tipo") or "", 48, placeholder="…"),
                    f"{a['km']:.1f}".replace(".", ",") if a.get("km") else "", str(a.get("min") or ""),
                    f"{a['fc_media']:.0f}" if a.get("fc_media") else "", f"{a['carga']:.0f}" if a.get("carga") else "",
                    EFECTO.get((a.get("efecto") or "").upper(), (a.get("efecto") or "").replace("_", " ").lower()))
            for (t, x, ha), v in zip(cab, vals):
                fig.text(x, y, v, fontsize=7.8, ha=ha, color=TINTA)
        pp.savefig(fig)
        plt.close(fig)
    return buf.getvalue()
