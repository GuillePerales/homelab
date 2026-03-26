# Ansible Roles

Roles reutilizables para configuración de hosts.

## Roles planificados

| Role | Descripción | Estado |
|---|---|---|
| `docker` | Instalar y configurar Docker daemon | ⏳ |
| `lxc-docker` | Configuración LXC para Docker (apparmor, cgroup2) | ⏳ |
| `k3s-node` | Instalar K3s en control plane o worker | ⏳ |
| `nfs-mounts` | Montar shares NFS desde nas-01 | ⏳ |
| `sops-age` | Distribuir clave Age para pipelines | ⏳ |

## Convención

```
roles/
└── nombre-rol/
    ├── tasks/main.yml
    ├── defaults/main.yml
    ├── handlers/main.yml
    └── README.md
```
