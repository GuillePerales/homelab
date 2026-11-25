# dozzle

Despliega el hub de Dozzle en docker-aux (grupo `monitoring`) con el compose del repo en
`/opt/dozzle`. Dozzle enseña en una web los logs de los contenedores **en vivo**, sin guardar
nada; para el historial haría falta Loki, que no está desplegado.

- **Hosts que ve:** docker-aux por el socket local, y docker-main y el NAS por sus agentes
  (`dozzle_remote_agents` en el `host_vars` de docker-aux; rol `dozzle_agent`).
- **Login obligatorio** (`DOZZLE_AUTH_PROVIDER=simple`): los logs pueden llevar tokens y URLs con
  passkey. El usuario `admin` se crea la primera vez con el propio comando `generate` de Dozzle; la
  contraseña llega por entorno (`DOZZLE_ADMIN_PASS`, de un fichero local fuera del repo) y por la
  entrada estándar, no por la línea de comandos. En el host solo queda su hash en
  `/srv/dozzle/data/users.yml`, que no se vuelve a generar. Para cambiarla: borrar ese fichero y
  relanzar el rol con la nueva.
- **El socket de Docker:** Dozzle lo monta para leer logs, pero el socket permite mucho más que leer.
  Por eso el login no es opcional y el hub solo vive en srv-net.
- Al final comprueba que el contenedor está `healthy` y que sin sesión la API responde 401.

Uso:

    DOZZLE_ADMIN_PASS=… ansible-playbook playbooks/monitoring.yml --tags dozzle
