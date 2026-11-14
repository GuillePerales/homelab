#!/usr/bin/env bash
# Lanza tofu con un token y la frase del estado de infrastructure/secrets/opentofu.yaml
# descifrados al vuelo.
# Uso: PROXMOX_VE_ENDPOINT=https://<nodo>:8006 ./tofu.sh plan|apply <subcomando de tofu> [args]
#   plan  -> token de solo lectura (opentofu@pve!plan)
#   apply -> token de escritura (opentofu@pve!apply)
set -euo pipefail
cd "$(dirname "$0")"
mode=${1:?plan o apply}
shift
case $mode in plan | apply) ;; *) echo "modo: plan o apply" >&2; exit 2 ;; esac
: "${PROXMOX_VE_ENDPOINT:?exporta PROXMOX_VE_ENDPOINT=https://<nodo>:8006}"
export PROXMOX_VE_INSECURE=${PROXMOX_VE_INSECURE:-true}
secrets=../../secrets/opentofu.yaml
TF_VAR_proxmox_api_token_id=$(sops -d --extract "[\"proxmox_${mode}_token_id\"]" "$secrets")
TF_VAR_proxmox_api_token_secret=$(sops -d --extract "[\"proxmox_${mode}_token_secret\"]" "$secrets")
TF_VAR_state_passphrase=$(sops -d --extract '["opentofu_state_passphrase"]' "$secrets")
export TF_VAR_proxmox_api_token_id TF_VAR_proxmox_api_token_secret TF_VAR_state_passphrase
exec tofu "$@"
