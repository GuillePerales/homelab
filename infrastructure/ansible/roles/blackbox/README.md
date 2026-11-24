# blackbox

Despliega Blackbox Exporter en docker-aux (grupo `monitoring`) con el compose del repo en
`/opt/blackbox`. Sondea por HTTP las mismas URL que vigila Gatus y deja en Prometheus la
disponibilidad, la latencia y la caducidad del certificado de cada servicio.

- **Una sola lista de servicios:** las URL se leen en cada ejecución del fichero de endpoints
  de Gatus (`blackbox_gatus_endpoints_file`, en docker-main) y se escriben como objetivos de
  Prometheus en `/srv/prometheus/config/targets/blackbox.yml`, un fichero que Prometheus
  recarga solo. Las IPs internas no entran nunca en el repo.
- **Dos módulos:** `http_reachable` y `http_insecure` (certificados autofirmados, el que
  Gatus marca con `client.insecure`). Ambos cuentan como correcto cualquier código HTTP por
  debajo de 500, igual que Gatus.
- **Sin alerta de caída:** de eso se encarga Gatus; Blackbox aporta el historial y las
  alertas de latencia y de certificados.

Uso:

    ansible-playbook playbooks/monitoring.yml --tags blackbox

Al añadir un servicio a Gatus, relanzar el rol para que Prometheus lo sondee también.
