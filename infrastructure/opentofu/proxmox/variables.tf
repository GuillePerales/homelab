variable "proxmox_api_token_id" {
  description = "ID del token de API de Proxmox (usuario!token)"
  type        = string
}

variable "proxmox_api_token_secret" {
  description = "Secreto del token de API de Proxmox (infrastructure/secrets/opentofu.yaml)"
  type        = string
  sensitive   = true
}

variable "k3s_ssh_public_key" {
  description = "Clave pública SSH que cloud-init instala en el usuario debian de k3s-01 (TF_VAR_k3s_ssh_public_key)"
  type        = string
}
