# OpenTofu — Proxmox

Provisioning de recursos Proxmox via API: VMs, LXCs, y configuración del cluster.

## Recursos a provisionar

| Recurso | Descripción | Fase |
|---|---|---|
| LXC docker-main | CT 200, pve-main, 10GB RAM, VLAN 30 | Phase 3 |
| LXC docker-aux | CT 201, pve-aux, 9GB RAM, VLAN 30 | Phase 3 |
| VM OPNsense | pve-router, 2 vCPU, 4GB RAM | Phase 1 |

## Provider

```hcl
terraform {
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.50"
    }
  }
}

provider "proxmox" {
  endpoint  = "https://192.168.1.135:8006"
  api_token = "${var.proxmox_api_token_id}=${var.proxmox_api_token_secret}"
  insecure  = true
}
```

## Variables requeridas

- `proxmox_api_token_id` — ID del API token Proxmox
- `proxmox_api_token_secret` — Secret del API token (via SOPS o variable de entorno)

## Uso

```bash
tofu init
tofu plan
tofu apply
```
