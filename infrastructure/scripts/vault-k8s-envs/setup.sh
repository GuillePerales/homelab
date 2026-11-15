#!/usr/bin/env bash
# Configura en Vault (K3s) el acceso por entorno: una política y un rol de Kubernetes
# por entorno, de modo que un pod de dev solo lee homelab/dev/* y uno de prod, homelab/prod/*.
# Idempotente. El token raíz no es un argumento: se lee de la entrada estándar.
#   python3 -c '...imprime el token...' | ./setup.sh
# Los valores de los secretos no están aquí: se cargan aparte con `vault kv put`.
set -euo pipefail
read -r VAULT_TOKEN
export VAULT_TOKEN
vault() { kubectl -n vault exec -i vault-0 -- env VAULT_TOKEN="$VAULT_TOKEN" vault "$@"; }

# Se captura la salida antes de buscar: con pipefail, grep -q corta la tubería y falla
auths=$(vault auth list -format=json)
[[ $auths == *'"kubernetes/"'* ]] || vault auth enable kubernetes
vault write auth/kubernetes/config kubernetes_host=https://kubernetes.default.svc:443
engines=$(vault secrets list -format=json)
[[ $engines == *'"homelab/"'* ]] || vault secrets enable -path=homelab kv-v2

for env in dev prod; do
  printf 'path "homelab/data/%s/*" {\n  capabilities = ["read"]\n}\n' "$env" |
    vault policy write "homelab-$env" -
  vault write "auth/kubernetes/role/homelab-check-$env" \
    bound_service_account_names=homelab-check \
    bound_service_account_namespaces="$env" \
    audience=https://kubernetes.default.svc.cluster.local \
    policies="homelab-$env" ttl=1h
done
