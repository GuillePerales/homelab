#!/usr/bin/env bash
# Lanza un playbook de Ansible desde WSL con el ~/.ssh/config de Windows, sin IPs escritas en el repo.
#
# Uso (desde cualquier carpeta del repo, dentro de WSL):
#   run-from-wsl.sh [monitoring.yml] [opciones de ansible-playbook...]
#   wsl -d Debian bash -lc 'cd /mnt/c/.../homelab && infrastructure/ansible/run-from-wsl.sh --check --diff'
#
# Qué resuelve:
#   - Exporta HEAD con `git archive` a una carpeta temporal: en Windows `core.autocrlf` deja el árbol
#     de trabajo en CRLF y Ansible no debe leerlo así. Lo que no está en un commit no se despliega.
#   - Resuelve la IP y el usuario de cada nodo del inventario con `ssh -G <alias>` sobre una copia del
#     ~/.ssh/config de Windows (que es el de WSL). Si el alias no está en el config, usa `monitoring_address` del host_vars.
#   - Copia la clave a un directorio de WSL con permisos 0600 (las rutas de Windows quedan en 0444).
#   - Los secretos entran por el entorno del que llama (PVE_EXPORTER_TOKEN, PBS_EXPORTER_TOKEN…); nunca
#     por la línea de comandos. Los roles conservan el del `.env` del host si no llegan.
#
# Variables: ANSIBLE_KEY (clave, por defecto ~/.ssh/homelab_ed25519), ANSIBLE_USERS="host=usuario ..."
# (usuario de los nodos que no están en el ~/.ssh/config; por defecto k3s-01=debian y el resto root).
set -euo pipefail

REPO="$(git -C "$(dirname "$(readlink -f "$0")")" rev-parse --show-toplevel)"
KEY_SRC="${ANSIBLE_KEY:-$HOME/.ssh/homelab_ed25519}"
USERS="${ANSIBLE_USERS:-k3s-01=debian}"

PLAYBOOK=monitoring.yml
if [[ $# -gt 0 && $1 != -* ]]; then PLAYBOOK="$1"; shift; fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
git -c safe.directory='*' -C "$REPO" archive HEAD infrastructure services | tar -x -C "$WORK"
install -d -m 700 "$WORK/key"
install -m 600 "$KEY_SRC" "$WORK/key/k"
# ssh de WSL rechaza el config de Windows por permisos: se resuelve sobre una copia 0600
install -m 600 "${ANSIBLE_SSH_CONFIG:-$HOME/.ssh/config}" "$WORK/key/config"

ANS="$WORK/infrastructure/ansible"
python3 - "$ANS" "$WORK" "$USERS" <<'PY'
import json, pathlib, subprocess, sys
import yaml
ans, work, users = pathlib.Path(sys.argv[1]), sys.argv[2], dict(u.split("=") for u in sys.argv[3].split())
inv = json.loads(subprocess.check_output(["ansible-inventory", "-i", str(ans / "inventory/hosts.yml"), "--list"], text=True))
hosts = sorted(inv["_meta"]["hostvars"])
conf = [f"Host *\n  IdentityFile {work}/key/k\n  IdentitiesOnly yes\n  StrictHostKeyChecking accept-new\n  UserKnownHostsFile {work}/key/known_hosts\n"]
for h in hosts:
    cfg = dict(l.split(" ", 1) for l in subprocess.check_output(["ssh", "-F", work + "/key/config", "-G", h], text=True).splitlines())
    vf = ans / "inventory/host_vars" / f"{h}.yml"
    vars_ = yaml.safe_load(vf.read_text()) or {} if vf.exists() else {}
    if cfg["hostname"] != h:                       # alias resuelto por el ~/.ssh/config
        host, user = cfg["hostname"], cfg["user"]
    else:                                          # sin alias: la IP de métricas del host_vars
        host, user = vars_["monitoring_address"], users.get(h, "root")
    conf.append(f"Host {h}\n  HostName {host}\n  User {user}\n")
    with vf.open("a") as f:
        f.write(f"\nansible_user: {user}\n")
(pathlib.Path(work) / "ssh.conf").write_text("\n".join(conf))
PY

export ANSIBLE_CONFIG="$ANS/ansible.cfg"
export ANSIBLE_SSH_ARGS="-F $WORK/ssh.conf -o ControlMaster=auto -o ControlPersist=60s"
cd "$ANS"
ansible-playbook -i inventory/hosts.yml "playbooks/$PLAYBOOK" "$@"
