"""Comprueba URLs del homelab y avisa a ntfy si alguna falla.

Configuración por entorno:
  CHECK_URLS  URLs separadas por comas (obligatoria)
  NTFY_URL    URL del topic de ntfy; si falta, solo escribe en la salida
  TIMEOUT     segundos por petición (por defecto 5)

Código de salida: 0 si todo responde, 1 si alguna falla.
"""
import os
import sys
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


def main() -> int:
    urls = [u.strip() for u in os.environ.get("CHECK_URLS", "").split(",") if u.strip()]
    if not urls:
        print("CHECK_URLS vacío", file=sys.stderr)
        return 2
    timeout = float(os.environ.get("TIMEOUT", "5"))
    failures = []
    for url in urls:
        reason = check(url, timeout)
        print(f"{'OK  ' if reason is None else 'FAIL'} {url}" + (f" ({reason})" if reason else ""))
        if reason:
            failures.append(f"{url}: {reason}")
    ntfy_url = os.environ.get("NTFY_URL")
    if failures and ntfy_url:
        notify(ntfy_url, "\n".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
