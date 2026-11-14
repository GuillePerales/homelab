variable "proxmox_api_token_id" {
  description = "ID del token de API de Proxmox (usuario!token)"
  type        = string
}

variable "proxmox_api_token_secret" {
  description = "Secreto del token de API de Proxmox (infrastructure/secrets/opentofu.yaml)"
  type        = string
  sensitive   = true
}
