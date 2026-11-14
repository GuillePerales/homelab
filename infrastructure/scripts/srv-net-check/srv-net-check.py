#!/usr/bin/env python3
"""Falla si un servicio conectado a srv-net no fija ipv4_address.

srv-net es una red macvlan compartida por varios hosts Docker de la misma VLAN.
El IPAM de Docker de cada host no ve las IPs de los demás, así que una IP
asignada automáticamente puede chocar con un contenedor de otro host. Por eso
todo servicio en srv-net lleva IP fija dentro del bloque de su host.

Uso: srv-net-check.py [ficheros...]  (sin argumentos, todos los compose del repo)
"""
import pathlib
import sys

import yaml

RED = "srv-net"


def errores(fichero):
    datos = yaml.safe_load(fichero.read_text()) or {}
    for nombre, servicio in (datos.get("services") or {}).items():
        redes = (servicio or {}).get("networks") or {}
        if isinstance(redes, list):
            if RED in redes:
                yield f"{fichero}: {nombre} está en {RED} sin ipv4_address"
        elif RED in redes and not (redes[RED] or {}).get("ipv4_address"):
            yield f"{fichero}: {nombre} está en {RED} sin ipv4_address"


def main(args):
    raiz = pathlib.Path(__file__).resolve().parents[3]
    ficheros = [pathlib.Path(a) for a in args] or sorted(
        raiz.glob("services/docker-compose/**/docker-compose.yml")
    )
    fallos = [e for f in ficheros for e in errores(f)]
    for f in fallos:
        print(f"::error::{f}")
    print(f"srv-net-check: {len(ficheros)} compose, {len(fallos)} sin IP fija")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
