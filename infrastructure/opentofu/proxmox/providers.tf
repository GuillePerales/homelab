# El endpoint (PROXMOX_VE_ENDPOINT) y PROXMOX_VE_INSECURE llegan por entorno para no
# publicar direcciones internas. El token, por variables: el de solo lectura en el CI
# (opentofu@pve!plan) y el de escritura solo en el portátil (opentofu@pve!apply).
provider "proxmox" {
  api_token = "${var.proxmox_api_token_id}=${var.proxmox_api_token_secret}"
}
