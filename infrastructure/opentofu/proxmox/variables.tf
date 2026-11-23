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
  description = "Clave pública SSH que cloud-init instala en el usuario debian de k3s-01"
  type        = string
  # Es pública: el valor por defecto deja que el plan del CI vea la misma VM sin un secreto más.
  default = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAII6OFGY349CjRxaagMV4EBwfQRmRQ0kFCJU8DxAuHwJ1 homelab-ansible"
}
