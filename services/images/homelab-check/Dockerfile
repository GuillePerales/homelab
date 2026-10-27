# Imagen de práctica de la fase 4: build -> Trivy -> registro de Forgejo.
# La base es un argumento para comparar CVE entre variantes:
#   docker build --build-arg BASE=python:3.13-slim .
#   docker build --build-arg BASE=python:3.13-alpine .
ARG BASE=python:3.13-slim
FROM ${BASE}

# Usuario sin privilegios (UID fijo, sin shell ni home): lo que no se necesita no se instala
RUN adduser --system --uid 10001 --no-create-home app 2>/dev/null \
    || adduser -S -u 10001 -H app

# pip es herramienta de construcción: la app no tiene dependencias y la imagen final no lo usa.
# Quitarlo elimina de raíz los CVE de sus librerías incluidas (msgpack, urllib3...) y superficie de ataque
RUN python -m pip uninstall -y pip

WORKDIR /app
COPY check.py .
USER 10001

ENTRYPOINT ["python", "/app/check.py"]
