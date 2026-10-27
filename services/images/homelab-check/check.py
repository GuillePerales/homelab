"""Comprueba URLs del homelab y avisa a ntfy si alguna falla.

Configuración por entorno:
  CHECK_URLS  URLs separadas por comas (obligatoria)
  NTFY_URL    URL del topic de ntfy; si falta, solo escribe en la salida
  TIMEOUT     segundos por petición (por defecto 5)
  INTERVAL    segundos entre rondas; si falta, hace una sola ronda y sale

Una sola ronda: código de salida 0 si todo responde, 1 si alguna falla.
En bucle avisa solo cuando cambia el estado (cae o se recupera), no en cada ronda.
"""
import os
import sys
import time
import urllib.request


def check(url: str, timeout: float) -> str | None:
    """Devuelve None si responde con 2xx/3xx, o el motivo del fallo."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return None if resp.status < 400 else f"HTTP {resp.status}"
    except Exception as exc:  # noqa: BLE001 - cualquier fallo cuenta como caído
        return str(exc)


def notify(ntfy_url: str, message: str) -> None:
    req = urllib.request.Request(
        ntfy_url,
        data=message.encode(),
        headers={"Title": "homelab-check", "Priority": "4"},
    )
    urllib.request.urlopen(req, timeout=5).close()


def run_round(urls: list[str], timeout: float) -> dict[str, str]:
    """Una ronda de comprobaciones; devuelve {url: motivo} de las que fallan."""
    failures = {}
    for url in urls:
        reason = check(url, timeout)
        print(f"{'OK  ' if reason is None else 'FAIL'} {url}" + (f" ({reason})" if reason else ""), flush=True)
        if reason:
            failures[url] = reason
    return failures


def main() -> int:
    urls = [u.strip() for u in os.environ.get("CHECK_URLS", "").split(",") if u.strip()]
    if not urls:
        print("CHECK_URLS vacío", file=sys.stderr)
        return 2
    timeout = float(os.environ.get("TIMEOUT", "5"))
    interval = float(os.environ.get("INTERVAL", "0"))
    ntfy_url = os.environ.get("NTFY_URL")

    failing: dict[str, str] = {}
    while True:
        now_failing = run_round(urls, timeout)
        if ntfy_url:
            new = [f"{u}: {r}" for u, r in now_failing.items() if u not in failing]
            recovered = [u for u in failing if u not in now_failing]
            if new:
                notify(ntfy_url, "Caído:\n" + "\n".join(new))
            if recovered:
                notify(ntfy_url, "Recuperado:\n" + "\n".join(recovered))
        failing = now_failing
        if interval <= 0:
            return 1 if failing else 0
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
