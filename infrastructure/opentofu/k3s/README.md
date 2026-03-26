# OpenTofu — K3s VMs

Provisioning de las VMs de Proxmox para el cluster K3s. Parte de Phase 4+.

## Recursos a provisionar

| Recurso | Nodo Proxmox | vCPU | RAM | Disco | IP |
|---|---|---|---|---|---|
| VM k3s-control | pve-main | 2 | 4GB | 40GB | 10.0.30.50 |
| VM k3s-worker | pve-aux | 2 | 3GB | 40GB | 10.0.30.51 |

## Notas

- SO: Ubuntu Server 22.04 LTS (cloud image)
- Red: VLAN 30 (SRV), bridge `vmbr0` con PVID 30
- Storage: `vault` pool en nas-01 via NFS
- K3s se instala con Ansible tras provisioning OpenTofu

## Dependencias

- Phase 4 completada (cluster Proxmox operativo)
- `infrastructure/opentofu/proxmox/` aplicado
- NFS storage cluster configurado en nas-01

## Uso

```bash
tofu init
tofu plan
tofu apply
# Tras apply, ejecutar playbook Ansible:
# ansible-playbook infrastructure/ansible/playbooks/k3s-install.yml
```
