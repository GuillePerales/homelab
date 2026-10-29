# Homelab

## Verificar un cambio

Lo mismo que corre el CI (`.github/workflows/lint.yml`, `.woodpecker/tofu-plan.yml`). Ejecutar lo que afecte al cambio y enseñar la salida:

- YAML: `yamllint -d relaxed services/docker-compose infrastructure/ansible .woodpecker .github`
- Ansible: `ansible-lint infrastructure/ansible/`
- OpenTofu: `cd infrastructure/opentofu/proxmox && tofu fmt -check -recursive && tofu init -backend=false && tofu validate`
- Compose: `docker compose config -q` en la carpeta del servicio tocado (con `--env-file .env.example` si lo tiene; el job `compose-validate` del CI rellena las variables que falten)
- Secretos: `bash infrastructure/scripts/sops-env/sops-env.sh check` (todo `sops.env` cifrado)
- README: `bash infrastructure/scripts/readme-check/readme-check.sh`
- Todo junto (yamllint, shellcheck, gitleaks, sops, README): `pre-commit run --all-files`

## Gotchas

- Repo **público**. El README y README-es son el escaparate de portfolio: tienen que reflejar el estado real del repo (servicios, fases, arquitectura) y nunca llevan IPs, rutas del NAS, puertos expuestos, usuarios ni dominios internos. `readme-check.sh` lo comprueba en pre-commit y en el CI.
- Los `.env` reales no están en el repo: los secretos van cifrados con SOPS + age en `sops.env` junto a cada compose.
- `tofu plan` necesita el token de Proxmox; en local basta con `validate`.
