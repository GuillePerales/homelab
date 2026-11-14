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

## Estado

El estado (`terraform.tfstate`) se versiona **cifrado** en este directorio con la encryption nativa de OpenTofu (`encryption.tf`: AES-GCM con clave PBKDF2, obligatoria también para los planes guardados). La frase está en `infrastructure/secrets/opentofu.yaml` (`opentofu_state_passphrase`) y en el secreto `tofu_state_passphrase` del CI.

Git no bloquea el estado como haría un backend remoto: los `apply` se hacen solo desde el portátil (único escritor), y antes de cada uno, `git pull`. El estado modificado se commitea en la misma rama que el cambio de código. Si algún día hay dos escritores, el paso es un backend con bloqueo (`tofu init -migrate-state`).

## Uso

```bash
export PROXMOX_VE_ENDPOINT=https://<nodo>:8006
tofu init
./tofu.sh plan plan     # token de solo lectura
./tofu.sh apply apply   # token de escritura
```

`tofu.sh` descifra el token y la frase del estado con SOPS al vuelo y lo pasa como `TF_VAR_*`; el endpoint llega por entorno para no publicar direcciones internas.
