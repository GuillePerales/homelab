#!/usr/bin/env python3
"""fan-control: curva de ventiladores propia para el Dell R230 (nas-01).

Por qué: sin tarjeta en la ranura PCIe, el firmware no cuenta con Fan1 (sensor
`Disabled`) y lo deja a su velocidad baja; justo delante está la bahía 0, con el
SSD que más se calienta. Fan1 solo acepta otra velocidad en modo manual, y el
modo manual es global, así que este script hace de iDRAC:

- Fan2-4 siguen a la CPU y a los HDD (el máximo de las dos curvas).
- Fan1 sigue al SSD de la bahía 0 (la temperatura que el iDRAC no ve), y nunca
  va por debajo de Fan2-4.
- Ante cualquier duda vuelve a automático: fallo al leer un sensor, CPU o
  entrada de aire por encima del límite, fichero de pausa o excepción.

Se lanza cada minuto desde una tarea cron de TrueNAS. Reenvía los valores en
cada pasada (si el iDRAC se reinicia y vuelve a automático, al minuto siguiente
recupera el control) y solo escribe en syslog (`fan-control`) cuando algo cambia.

Uso: fan-control.py [--dry-run]   (--dry-run: calcula y muestra, no envía nada)
Pausa: crear el fichero PAUSA (ver .env.example) -> automático hasta borrarlo.
Configuración privada (no versionada): /mnt/vault/secrets/fan-control.env
"""
import os
import re
import subprocess
import sys



def load_env(path):
    env = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"')
    return env


ENV = load_env(os.environ.get("ENV_FILE", "/mnt/vault/secrets/fan-control.env"))
# Discos por /dev/disk/by-id (las letras sdX pueden cambiar al reiniciar).
SSD_BAHIA0 = ENV["SSD_BAHIA0"]
HDDS = [d for d in ENV.get("HDDS", "").split(",") if d]
PAUSA = ENV.get("PAUSA", "/mnt/vault/secrets/fan-control.pausa")
ESTADO = "/run/fan-control.estado"  # tmpfs: se pierde al reiniciar, a propósito

# Límites que devuelven el control al iDRAC (°C).
CPU_MAX = 75
INLET_MAX = 35

# Curvas: (temp_baja, pct_bajo, temp_alta, pct_alto), lineal entre medias.
CURVA_CPU = (45, 22, 70, 60)
CURVA_HDD = (40, 22, 48, 50)
CURVA_SSD = (38, 30, 55, 100)
PCT_MIN = 22

# IDs de ventilador para `raw 0x30 0x30 0x02 <id> <pct>` (Fan1 = 0x00).
FAN1 = 0x00
TODOS = 0xFF


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=20)


def log(msg):
    print(msg)
    run(["logger", "-t", "fan-control", msg])


def curva(t, c):
    t0, p0, t1, p1 = c
    if t <= t0:
        return p0
    if t >= t1:
        return p1
    return round(p0 + (p1 - p0) * (t - t0) / (t1 - t0))


def temps_ipmi():
    """Devuelve (inlet, cpu) del SDR; lanza excepción si falta alguno."""
    out = run(["ipmitool", "sdr", "type", "Temperature"]).stdout
    vals = {}
    for linea in out.splitlines():
        campos = [c.strip() for c in linea.split("|")]
        m = re.match(r"(\d+) degrees C", campos[-1]) if len(campos) == 5 else None
        if m:
            vals[campos[0]] = int(m.group(1))
    return vals["Inlet Temp"], vals["Temp"]


def temp_disco(dev, puede_dormir=False):
    """Temperatura SMART (atributo 194). None si el HDD está en reposo."""
    args = ["smartctl", "-A", dev]
    if puede_dormir:
        args[1:1] = ["-n", "standby"]
    r = run(args)
    if puede_dormir and r.returncode == 2:  # en standby: no se despierta
        return None
    for linea in r.stdout.splitlines():
        if linea.split()[:2] == ["194", "Temperature_Celsius"]:
            return int(linea.split()[9])
    raise RuntimeError(f"sin temperatura SMART en {dev}")


def ipmi_raw(*bytes_):
    r = run(["ipmitool", "raw", "0x30", "0x30", *[f"0x{b:02x}" for b in bytes_]])
    if r.returncode != 0:
        raise RuntimeError(f"ipmitool raw {bytes_}: {r.stderr.strip()}")


def automatico(dry):
    if not dry:
        ipmi_raw(0x01, 0x01)


def estado_anterior():
    try:
        with open(ESTADO) as f:
            return f.read().strip()
    except OSError:
        return ""


def guardar_estado(s, dry):
    if dry:
        return
    if s != estado_anterior():
        log(s)
    with open(ESTADO, "w") as f:
        f.write(s)


def main(dry):
    if os.path.exists(PAUSA):
        automatico(dry)
        guardar_estado("auto: pausa manual (existe el fichero de pausa)", dry)
        return

    inlet, cpu = temps_ipmi()
    ssd = temp_disco(SSD_BAHIA0)
    hdds = [t for t in (temp_disco(d, puede_dormir=True) for d in HDDS) if t is not None]

    if cpu >= CPU_MAX or inlet >= INLET_MAX:
        automatico(dry)
        guardar_estado(f"auto: limite superado (cpu {cpu}, entrada {inlet})", dry)
        return

    base = max(PCT_MIN, curva(cpu, CURVA_CPU), *(curva(t, CURVA_HDD) for t in hdds))
    fan1 = max(base, curva(ssd, CURVA_SSD))

    resumen = (f"manual: Fan2-4 {base}% Fan1 {fan1}% "
               f"(cpu {cpu}, entrada {inlet}, ssd0 {ssd}, hdd {hdds or 'reposo'})")
    if dry:
        print("[dry-run]", resumen)
        return
    ipmi_raw(0x01, 0x00)          # modo manual
    ipmi_raw(0x02, TODOS, base)   # Fan1-4 a la base...
    ipmi_raw(0x02, FAN1, fan1)    # ...y Fan1 a su valor
    guardar_estado(resumen.split(" (")[0], dry)
    print(resumen)


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    try:
        main(dry)
    except Exception as e:  # cualquier fallo: el iDRAC vuelve a mandar
        try:
            automatico(dry)
        finally:
            log(f"auto: error, control devuelto al iDRAC: {e}")
        sys.exit(1)
