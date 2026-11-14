# OpenTofu — Proxmox

Infraestructura del clúster Proxmox como código con OpenTofu y el provider [`bpg/proxmox`](https://registry.opentofu.org/providers/bpg/proxmox).

## Importar antes que crear

Los recursos existían antes de la IaC, así que se **importan** (bloques `import` en `imports.tf`) en lugar de crearse. La prueba de que el código describe la realidad es un `plan` sin cambios reales.

| Recurso | Fichero | Qué es |
|---|---|---|
| VM 100 `fw-01` | `vm.tf` | OPNsense (firewall y router) |
| CT 200 `docker-main` | `containers.tf` | LXC privilegiado con Docker |
| CT 201 `docker-aux` | `containers.tf` | LXC no privilegiado con Docker |

Límites conocidos:

- Las líneas `lxc.*` en crudo de los contenedores (AppArmor, dispositivos, bind mounts) no existen en el provider: solo `root@pam` con contraseña puede escribirlas. Viven fuera de OpenTofu.
- El import de bpg no rellena `vm_id` ni algunos ajustes propios del provider (`timeout_start`, `reboot_after_update`): el primer `plan` los muestra como cambios solo de estado.
- La VM del firewall lleva `reboot_after_update = false` y todos los recursos `prevent_destroy`.

## Credenciales

Usuario de Proxmox dedicado con dos tokens (`privsep`), cifrados con SOPS en `infrastructure/secrets/opentofu.yaml`:

| Token | Rol | Dónde se usa |
|---|---|---|
| `plan` | `PVEAuditor` (solo lectura) | CI (`.woodpecker/tofu-plan.yml`) |
| `apply` | Rol propio limitado a VMs, LXC y almacenamiento | Solo en el portátil de administración |

## Uso

```bash
export PROXMOX_VE_ENDPOINT=https://<nodo>:8006
tofu init
./tofu.sh plan plan     # token de solo lectura
./tofu.sh apply apply   # token de escritura
```

`tofu.sh` descifra el token con SOPS al vuelo y lo pasa como `TF_VAR_*`; el endpoint llega por entorno para no publicar direcciones internas.
