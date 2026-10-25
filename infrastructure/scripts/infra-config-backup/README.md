# infra-config-backup

Copia diaria de la configuración de los hosts que PBS no cubre (PBS copia las VM y los CT, no los hosts). Corre en el NAS y deja un `.tar.gz` por host y día; se guardan 30 días.

| Host | Qué se copia | Comando fijo en `authorized_keys` del host |
|---|---|---|
| OPNsense | `/conf/config.xml` | `tar -C /conf -czf - config.xml` |
| Nodos Proxmox | `/etc` relevante y la BD del clúster | ver abajo |
| TrueNAS (local) | `freenas-v1.db` (copia consistente con `sqlite3 .backup`) y `pwenc_secret` | — |

## Instalación

1. Clave propia en el NAS, sin contraseña:
   `ssh-keygen -t ed25519 -N '' -C infra-config-backup -f /mnt/vault/secrets/ssh/backup-infra_ed25519`
2. En **OPNsense** la clave de root se añade en la web (*System → Access → Users → root → Authorized keys*); si se edita el fichero a mano, OPNsense lo sobrescribe:
   `from="<IP del NAS>",command="tar -C /conf -czf - config.xml",no-pty,no-port-forwarding,no-agent-forwarding,no-X11-forwarding ssh-ed25519 AAAA… infra-config-backup`
3. En **Proxmox**, `/root/.ssh/authorized_keys` es un enlace a `/etc/pve/priv/authorized_keys`, compartido por el clúster: una línea vale para todos los nodos.
   `from="<IP del NAS>",command="tar -C / -czf - --ignore-failed-read etc/pve etc/network etc/hosts etc/hostname etc/resolv.conf etc/apt etc/systemd/system etc/ssh etc/cron.d etc/vzdump.conf etc/modprobe.d etc/default etc/corosync var/lib/pve-cluster/config.db",no-pty,no-port-forwarding,no-agent-forwarding,no-X11-forwarding ssh-ed25519 AAAA… infra-config-backup`
4. `known_hosts` junto a la clave, con la huella de cada host: `ssh-keyscan <host> >> /mnt/vault/secrets/ssh/known_hosts`.
5. `.env` en `/mnt/vault/secrets/infra-config-backup.env` (ver `infra-config-backup.env.example`).
6. Cron de TrueNAS diario a las 04:00, antes de `backup-offsite`.

## Restaurar

- **OPNsense**: instalación limpia → *System → Configuration → Backups → Restore* con el `config.xml`.
- **Proxmox**: reinstalar el nodo con el mismo nombre e IP, copiar `etc/network/interfaces` y reiniciar; si se perdió todo el clúster, parar `pve-cluster` y devolver `var/lib/pve-cluster/config.db`. Las VM y los CT vuelven desde PBS.
- **TrueNAS**: *System → General → Manage Configuration → Upload Config* con un tar que tenga `freenas-v1.db` y `pwenc_secret`.
