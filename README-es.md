# Infraestructura Homelab

Homelab personal gestionado íntegramente como Infraestructura como Código. Dos objetivos en paralelo: un stack self-hosted privado que sustituye servicios cloud, y un pipeline DevOps de nivel productivo construido con las mismas herramientas que se usan en entornos enterprise.

**Versión:** 3.2 — Marzo 2026
**Estado:** Phase 4 en curso

---

## Tabla de Contenidos

1. [Historial de Fases](#1-historial-de-fases)
2. [Hardware](#2-hardware)
3. [Red e Infraestructura](#3-red-e-infraestructura)
4. [Servicios](#4-servicios)
5. [Virtualización](#5-virtualización)
6. [Almacenamiento](#6-almacenamiento)
7. [Acceso Remoto](#7-acceso-remoto)
8. [DevOps e IaC](#8-devops-e-iac)

---

## 1. Historial de Fases

### Phase 1 — Red (✅ Completada)

| Aspecto | Antes | Después |
|---|---|---|
| Topología de red | Teórica | Dual-switch implementado (router ISP + switch gestionado) |
| VLANs | Concepto | 7 VLANs operativas con políticas de salida por VLAN |
| DHCP | Genérico | Dnsmasq por VLAN con reservas estáticas |
| VPN remota | WireGuard (planificado) | Tailscale implementado — funciona con CGNAT, sin puertos abiertos |
| Reglas de firewall | Teóricas | Implementadas con aislamiento inter-VLAN y accesos selectivos |

### Phase 2 — Almacenamiento y Multimedia (✅ Completada)

| Aspecto | Resultado |
|---|---|
| NAS | TrueNAS Scale en Dell R230 |
| Almacenamiento | Pools ZFS: `tank` (stripe HDD) + `vault` (mirror SSD) |
| Stack multimedia | Sonarr, Radarr, Lidarr, Prowlarr, Bazarr, qBittorrent — todos operativos |
| Backup | Proxmox Backup Server (PBS) en Docker en el NAS |
| Sincronización | Syncthing para sync con dispositivos móviles |

### Phase 3 — Clúster y Gestión de Contenedores (✅ Completada)

| Aspecto | Antes | Después |
|---|---|---|
| Proxmox | Nodo único | **Clúster de 3 nodos: pve-router + pve-main + pve-aux** |
| docker-main | No existía | LXC Debian 12, VLAN 30, 10GB RAM |
| docker-aux | No existía | LXC Debian 12, VLAN 30, 9GB RAM |
| Red macvlan | Solo NAS | Los 3 hosts Docker con rangos no solapados |
| Portainer | No existía | Server en docker-main + Agents en aux y nas |
| Almacenamiento NFS clúster | Solo NAS | `tank/vms/images` montado en pve-main y pve-aux |

---

## 2. Hardware

### Nodos de producción (24/7)

| ID | Dispositivo | Especificaciones | Rol |
|---|---|---|---|
| HW-SRV-01 | Dell R230 | 16GB RAM, 6TB HDD, 800GB SSD | NAS / TrueNAS Scale |
| HW-SRV-02 | Mini PC (quad-NIC) | 20GB RAM | Proxmox router + OPNsense VM |
| HW-SRV-03 | Mini PC | 16GB RAM, 256GB SSD, 1TB HDD | Nodo Proxmox principal |
| HW-SRV-04 | Mini PC | 10GB RAM | Nodo Proxmox secundario |
| HW-IOT-01 | Raspberry Pi 4 | 4GB RAM | DNS failover / utilidades |

Todos los nodos de producción funcionan 24/7. El consumo total en idle es inferior a 100W.

### Estaciones de trabajo

| ID | Dispositivo | Especificaciones | Rol |
|---|---|---|---|
| HW-WKS-01 | PC de sobremesa | 32GB DDR5, Ryzen 7 9700X | Estación de trabajo principal |
| HW-WKS-02 | PC de sobremesa | 32GB DDR4, i7-7700K | Secundaria / estación de desarrollo |

---

## 3. Red e Infraestructura

### 3.1 Topología dual-switch

#### Switch 1: Router ISP

- Sin VLANs, gestiona `192.168.1.0/24`
- Conecta: Internet ↔ gestión Proxmox + WAN OPNsense
- **Justificación:** Gestión Proxmox aquí = siempre accesible independientemente del estado de OPNsense

#### Switch 2: TP-Link TL-SG108E (gestionado)

- VLANs 802.1Q, gestiona `10.0.x.0/24`
- Conecta: OPNsense ↔ todo el hardware físico en VLAN 5
- **Justificación:** Hardware físico aquí = independiente de OPNsense

```
                      INTERNET
                          │
                   Router ISP (192.168.1.0/24)
                   └─ Gestión Proxmox (em0)
                   └─ WAN OPNsense (igb0, DHCP)
                          │
                  HW-SRV-02 (pve-router)
                          │
                igb3 → TL-SG108E (aware de VLANs)
                          │
         ┌────────────────┼──────────────────┐
      VLAN 5           VLAN 10            VLAN 30
      (INFRA)          (MGMT)             (SRV)
    bare metal      virtualizado         servicios
    nas-01          fw-01                docker-main
    pve-main        prx-01               docker-aux
    pve-aux         auth-01              K3s (planificado)
    wks-01/02
    rpi-dns
```

### 3.2 Segmentación VLAN

| VLAN | Nombre | Subred | Salida | Propósito |
|---|---|---|---|---|
| 5 | INFRA | 10.0.5.0/24 | ISP directo | Hardware físico: Proxmox, TrueNAS, IPMI, RPi |
| 10 | MGMT | 10.0.10.0/24 | ISP directo | Servicios virtualizados: OPNsense, NGINX, Authentik |
| 15 | AI | 10.0.15.0/24 | ISP directo | Agentes AI (OpenClaw) — firewall estricto |
| 20 | DEVICES | 10.0.20.0/24 | ProtonVPN | Dispositivos personales |
| 30 | SRV | 10.0.30.0/24 | ProtonVPN + kill switch | Stacks Docker, workloads K3s |
| 50 | IOT | 10.0.50.0/24 | ProtonVPN | IoT no confiable — solo internet |
| 99 | GUEST | 10.0.99.0/24 | ProtonVPN | Invitados — solo internet |

**Separación crítica: INFRA vs MGMT**

- **VLAN 5 (INFRA):** Capa física. Hardware en el switch gestionado. ✅ Funciona aunque OPNsense esté caído.
- **VLAN 10 (MGMT):** Capa virtualizada. Servicios en VMs. ❌ Cae si OPNsense falla. Pero ✅ INFRA permanece accesible.

### 3.3 Configuración de puertos del switch (TL-SG108E)

| VLAN | P1 | P2 | P3 | P4 | P6 | Descripción |
|---|---|---|---|---|---|---|
| 5 (INFRA) | T | U | U | U | U | Hardware físico |
| 10 (MGMT) | T | - | - | - | - | Servicios virtualizados |
| 15 (AI) | T | - | - | - | - | VLAN AI aislada |
| 30 (SRV) | T | - | - | - | **T** | Servicios — **P6 Tagged requerido para contenedores NAS** |
| 50 (IOT) | T | - | - | - | - | IoT aislado |

> **P6 VLAN 30 Tagged:** Necesario para que los contenedores Docker en el NAS con direcciones macvlan `srv-net` sean accesibles desde fuera del NAS. Sin esto, el tráfico VLAN 30 queda confinado dentro del NAS.

**Leyenda:** T=Tagged, U=Untagged, -=No miembro

| Puerto | Dispositivo | VLAN | Rol |
|---|---|---|---|
| P1 | pve-router igb3 | Trunk (todas las VLANs tagged) | Trunk router OPNsense |
| P2 | pve-aux | INFRA (5), untagged | Nodo Proxmox |
| P3 | wks-02 | INFRA (5), untagged | Estación de desarrollo |
| P4 | pve-main | INFRA (5), untagged | Nodo Proxmox |
| P6 | nas-01 | INFRA (5) untagged + SRV (30) tagged | NAS |
| P8 | wks-01 | INFRA (5), untagged | Estación de trabajo principal |

### 3.4 Rangos DHCP por VLAN (Dnsmasq en OPNsense)

| VLAN | Rango dinámico | Reservas estáticas |
|---|---|---|
| 5 (INFRA) | .100–.200 | nas-01, pve-main, pve-aux, wks-01, wks-02, rpi-dns |
| 10 (MGMT) | .100–.200 | OPNsense, NGINX, Authentik |
| 30 (SRV) | .100–.254 | `.10–.57` reservado para contenedores macvlan |
| 50 (IOT) | .100–.200 | — |

### 3.5 Rangos de direcciones macvlan (VLAN 30 — sin solapamiento)

| Host | Interfaz | Rango asignado |
|---|---|---|
| docker-nas (nas-01) | eno1.30 | 10.0.30.10–.25 |
| docker-main (LXC pve-main) | eth0 | 10.0.30.26–.41 |
| docker-aux (LXC pve-aux) | eth0 | 10.0.30.42–.57 |
| DHCP dinámico | — | 10.0.30.100+ |

### 3.6 Reglas de firewall (OPNsense) — políticas clave

```
INFRA → puede alcanzar: INFRA, MGMT, SRV, internet
MGMT  → puede alcanzar: INFRA, SRV, internet
SRV   → puede alcanzar: SRV (intra), internet vía ProtonVPN (kill switch activo)
IOT   → puede alcanzar: solo internet (ProtonVPN)
AI    → puede alcanzar: internet (restringido), sin acceso a otras VLANs
```

---

## 4. Servicios

### Nomenclatura

```
Formato: [categoría]-[función]-[instancia]

Categorías:
  fw   = Firewall/Router      prx  = Proxy
  dns  = DNS                  auth = Autenticación
  mon  = Monitorización       nas  = Almacenamiento
  media = Multimedia          arr  = Gestión de contenidos
  dev  = Desarrollo           ai   = Inteligencia Artificial
  app  = Aplicaciones         bkp  = Backup
```

### 4.1 Infraestructura física (VLAN 5 — INFRA)

| ID | Servicio | Host | Tipo | Función |
|---|---|---|---|---|
| infra-pve-01 | Proxmox VE | pve-router | Bare Metal | Hipervisor + host OPNsense |
| infra-pve-02 | Proxmox VE | pve-main | Bare Metal | Hipervisor principal |
| infra-pve-03 | Proxmox VE | pve-aux | Bare Metal | Hipervisor secundario |
| infra-nas-01 | TrueNAS Scale | nas-01 | Bare Metal | NAS — ZFS, NFS, Docker |
| infra-ipmi-01 | iDRAC/IPMI | nas-01 | Firmware | Gestión de hardware Dell |
| infra-rpi-01 | Raspberry Pi | rpi-dns | Bare Metal | DNS failover + utilidades |

### 4.2 Gestión (VLAN 10 — MGMT)

| ID | Servicio | Host | Tipo | Puerto | Función |
|---|---|---|---|---|---|
| fw-opnsense-01 | OPNsense | pve-router | VM | 443 | **Firewall, NAT, DHCP, VLANs, Tailscale** |
| prx-nginx-01 | NGINX Proxy Manager | pve-router | LXC | 81 | Reverse proxy + SSL Let's Encrypt |
| auth-authentik-01 | Authentik | pve-router | LXC | 9000 | SSO / Identity Provider |

### 4.3 DNS

| ID | Servicio | Host | Función |
|---|---|---|---|
| dns-unbound-01 | Unbound (integrado en OPNsense) | fw-01 | Resolver recursivo + DNSSEC + split-horizon |
| dns-rpi-01 | Unbound backup | rpi-dns | DNS failover (futuro) |

> **Decisión de diseño:** Unbound integrado en OPNsense en lugar de AdGuard Home. Justificación: sin servicios adicionales que mantener, soporte nativo de DNSSEC y split-horizon para el dominio `.homelab`.

### 4.4 Monitorización (VLAN 30 — SRV)

> Phase 8 — planificado en `docker-aux`, rango macvlan `.42–.57`

| ID | Servicio | Host | Puerto | Función |
|---|---|---|---|---|
| mon-prometheus-01 | Prometheus | docker-aux | 9090 | Base de datos de métricas + alertas |
| mon-grafana-01 | Grafana | docker-aux | 3001 | Dashboards — métricas DORA, salud de infra |
| mon-loki-01 | Loki | docker-aux | 3100 | Agregación centralizada de logs |
| mon-uptime-01 | Uptime Kuma | docker-aux | 3002 | Monitorización de disponibilidad |
| mon-speedtest-01 | Speedtest Tracker | docker-aux | 8765 | Tests de velocidad automatizados |
| mon-homepage-01 | Homepage | docker-aux | 3003 | Dashboard de inicio |
| mon-nodeexp-01 | Node Exporter | Todos los hosts | 9100 | Métricas CPU, RAM, disco |
| mon-ipmi-01 | IPMI Exporter | docker-aux | 9290 | Métricas de hardware Dell |

### 4.5 Almacenamiento de usuario (VLAN 30 — SRV)

| ID | Servicio | Host | Tipo | Función |
|---|---|---|---|---|
| app-nextcloud-01 | Nextcloud | docker-main | Docker | Cloud personal: archivos, calendario, contactos |
| app-immich-01 | Immich | docker-main | Docker | Gestión de fotos/vídeo (alternativa a Google Photos) |
| app-syncthing-01 | Syncthing | docker-nas | Docker macvlan | ✅ Sync P2P con dispositivos móviles |
| app-paperless-01 | Paperless-ngx | docker-main | Docker | Gestión documental con OCR |

### 4.6 Multimedia (VLAN 30 — SRV)

> Jellyfin y Overseerr planificados para Phase 7 en `docker-main`.

| ID | Servicio | Host | Tipo | Puerto | Estado | Función |
|---|---|---|---|---|---|---|
| media-jellyfin-01 | Jellyfin | docker-main | Docker macvlan | 8096 | ⏳ Phase 7 | Servidor de streaming multimedia |
| media-overseerr-01 | Overseerr | docker-main | Docker macvlan | 5055 | ⏳ Phase 7 | Portal de peticiones multimedia |
| arr-sonarr-01 | Sonarr | docker-nas | Docker macvlan | 8989 | ✅ Operativo | Gestión automática de series |
| arr-radarr-01 | Radarr | docker-nas | Docker macvlan | 7878 | ✅ Operativo | Gestión automática de películas |
| arr-lidarr-01 | Lidarr | docker-nas | Docker macvlan | 8686 | ✅ Operativo | Gestión automática de música |
| arr-prowlarr-01 | Prowlarr | docker-nas | Docker macvlan | 9696 | ✅ Operativo | Gestor centralizado de indexers |
| arr-bazarr-01 | Bazarr | docker-nas | Docker macvlan | 6767 | ✅ Operativo | Descarga automática de subtítulos |
| media-qbittorrent-01 | qBittorrent | docker-nas | Docker macvlan | 8080 | ✅ Operativo | Cliente de descargas web (enrutado por ProtonVPN) |

### 4.7 DevOps (VLAN 30 — SRV)

| ID | Servicio | Host | Tipo | Puerto | Estado | Función |
|---|---|---|---|---|---|---|
| dev-portainer-01 | Portainer | docker-main | Docker macvlan | 9443 | ✅ Operativo | UI de gestión multi-host de contenedores |
| dev-forgejo-01 | Forgejo | docker-main | Docker macvlan | 3000 | 🔄 Phase 4 | Servidor Git self-hosted |
| dev-woodpecker-01 | Woodpecker CI | docker-main | Docker macvlan | 8000 | 🔄 Phase 4 | Pipelines CI/CD |
| dev-harbor-01 | Harbor | docker-main | Docker (IP LXC) | 80/443 | 🔄 Phase 4 | Registry privado de contenedores |
| dev-jenkins-01 | Jenkins | Worker K3s | Helm | 8080 | ⏳ Phase 4+ | Pipelines CI/CD de aplicaciones |
| dev-argocd-01 | ArgoCD | Worker K3s | Helm | 443 | ⏳ Phase 4+ | Entrega continua GitOps |
| dev-sonarqube-01 | SonarQube | Worker K3s | Helm | 9000 | ⏳ Phase 4+ | Quality gate de código |
| dev-vault-01 | HashiCorp Vault | Worker K3s | Helm | 8200 | ⏳ Phase 4+ | Gestión de secretos dinámicos |
| dev-awx-01 | AWX | Worker K3s | Operator | 80 | ⏳ Phase 4+ | UI de automatización Ansible |

### 4.8 IA (VLAN 15 — AI)

| ID | Servicio | Host | Tipo | Puerto | Estado | Función |
|---|---|---|---|---|---|---|
| ai-openclaw-01 | OpenClaw | pve-router | LXC | 18789 | ⏳ Phase 9 | Agente IA para automatización del homelab |

### 4.9 Backup

| ID | Servicio | Host | Tipo | Puerto | Estado | Función |
|---|---|---|---|---|---|---|
| bkp-pbs-01 | Proxmox Backup Server | nas-01 | Docker | 8007 | ✅ Operativo | Backups de VMs/LXCs al NAS |

**Total: 35+ servicios en 3 hosts Docker + NAS + 3 nodos Proxmox + OPNsense**

---

## 5. Virtualización

### 5.1 Clúster Proxmox (3 nodos)

| Nodo | Hardware | RAM | Rol |
|---|---|---|---|
| pve-router | Mini PC (quad-NIC) | 20GB | Router + servicios de gestión |
| pve-main | Mini PC | 16GB | Cargas Docker principales, control plane K3s |
| pve-aux | Mini PC | 10GB | Servicios auxiliares, worker K3s |

### 5.2 Distribución de cargas

**pve-router (20GB)**
- `fw-opnsense-01` (VM, 4GB) — Firewall OPNsense
- `prx-nginx-01` (LXC, 512MB) — Reverse proxy *(Phase 5)*
- `auth-authentik-01` (LXC, 1GB) — SSO *(Phase 5)*
- `ai-openclaw-01` (LXC, 4GB) — Agente IA *(Phase 9)*

**pve-main (16GB)**
- `docker-main` (LXC, 10GB) ✅ — Portainer, Forgejo, Woodpecker, Harbor

**pve-aux (10GB)**
- `docker-aux` (LXC, 6GB tras Phase 4+) ✅ — Monitorización, servicios cloud
- VM worker K3s (3GB) — Stack DevOps *(Phase 4+)*

### 5.3 Decisión VM vs LXC

| Tipo de carga | Uso | Motivo |
|---|---|---|
| OPNsense | VM | Necesita su propio kernel |
| Nodos K3s | VM | Requiere módulos de kernel (ip_tables, nf_conntrack, br_netfilter) que los LXCs restringen |
| Todo lo demás | LXC | Ahorra ~600MB RAM idle por instancia |

### 5.4 Configuración LXC para Docker

```ini
# /etc/pve/lxc/<CTID>.conf — requerido antes del primer arranque
lxc.apparmor.profile: unconfined
lxc.cgroup2.devices.allow: a
lxc.cap.drop:
features: keyctl=1
```

> **Advertencia:** NO añadir `nesting=1` junto con `apparmor: unconfined` — entran en conflicto y el LXC fallará al arrancar.

---

## 6. Almacenamiento

### 6.1 Pools ZFS

| Pool | Discos | Capacidad | Layout | Propósito |
|---|---|---|---|---|
| `tank` | 2x HDD 3TB | ~6TB | Stripe | Datos de alto volumen y reemplazables |
| `vault` | 2x SSD 800GB | ~400GB útiles | Mirror RAID-1 | Datos críticos: rápido y redundante |

### 6.2 Estructura de datasets

```
tank  (~6TB — stripe HDD)
├── backups/
│   ├── proxmox/      ← Datastore PBS
│   ├── databases/
│   └── configs/
├── downloads/
│   ├── complete/
│   └── incomplete/
├── media/
│   ├── movies/ tv/ music/
│   └── isos/
└── vms/
    └── images/       ← Almacenamiento NFS clúster Proxmox

vault  (~400GB — mirror SSD)
├── apps/             ← Appdata de contenedores (NFS → hosts Docker)
├── docker/           ← Docker daemon data-root (NFS → hosts Docker)
├── documents/        ← Documentos personales (NFS + SMB)
├── git-storage/      ← Repositorios Forgejo
└── secrets/          ← Claves Age, claves SSH, certificados
```

### 6.3 Shares NFS

| Share | Ruta | Acceso | Notas |
|---|---|---|---|
| media | /tank/media | VLAN 30, INFRA | Jellyfin, \*arr |
| downloads | /tank/downloads | VLAN 30 | qBittorrent, staging |
| backups | /tank/backups | Solo VLAN 5 | Solo PBS y Restic |
| vms | /tank/vms | VLAN 5 | Almacenamiento compartido clúster Proxmox |
| vault/apps | /vault/apps | VLAN 30 | Appdata Docker (SSD) |
| vault/docker | /vault/docker | VLAN 30 | Docker data-root (SSD) |
| vault/git-storage | /vault/git-storage | VLAN 30, INFRA | Repos Forgejo |

---

## 7. Acceso Remoto

**Tailscale** funciona como subnet router plugin dentro de OPNsense, anunciando el rango completo `10.0.0.0/8`. Esto proporciona acceso a todas las VLANs y servicios desde cualquier dispositivo con cliente Tailscale.

**Por qué Tailscale y no WireGuard tradicional:** El ISP usa CGNAT sin IPv4 pública. WireGuard tradicional requiere un endpoint público para recibir conexiones, lo que es imposible bajo CGNAT. Tailscale usa su servidor de coordinación para establecer túneles peer-to-peer mediante NAT traversal — sin necesidad de abrir puertos en el router ISP.

Clientes Tailscale: estación de trabajo principal, dispositivos móviles.

---

## 8. DevOps e IaC

### 8.1 Filosofía y Decisiones de Arquitectura

El stack DevOps replica un entorno enterprise real usando exclusivamente herramientas open-source y gratuitas. Cada herramienta tiene un equivalente corporativo directo, permitiendo demostrar experiencia práctica sin haber trabajado en una empresa DevOps.

| Decisión | Elección | Motivo |
|---|---|---|
| Git privado (IaC, configs) | **Forgejo** | Ligero, self-hosted, <200MB RAM |
| Git público (proyectos, CV) | **GitHub / GitLab.com** | Visibilidad, Actions/CI gratuito |
| CI/CD infraestructura | **Woodpecker CI** | Webhooks nativos con Forgejo, YAML idéntico a GitHub Actions |
| CI/CD aplicaciones | **Jenkins** | Estándar de facto en empresas españolas, especialmente banca |
| Registry de contenedores | **Harbor** | Estándar CNCF, Trivy integrado, políticas a nivel de proyecto |
| Orquestación (stack DevOps) | **K3s** | Mismo API que EKS/AKS/GKE, ~512MB idle |
| Orquestación (servicios personales) | **Docker Compose** | Los servicios estables no necesitan scheduling ni rolling updates de K8s |
| GitOps | **ArgoCD** | Pull-based, declarativo, usado directamente en producción enterprise |
| IaC provisioning | **OpenTofu** | Fork open-source de Terraform, 100% compatible HCL, licencia MPL-2.0 |
| IaC configuración | **Ansible + AWX** | Estándar de la industria, igual en homelab que en empresas |
| Gestor de paquetes K8s | **Helm** | Estándar para desplegar aplicaciones en Kubernetes |
| Secretos en Git | **SOPS + Age** | Cifrado de archivos antes del commit, ya operativo |
| Secretos en K8s | **HashiCorp Vault** | Secretos dinámicos, auto-rotación, estándar enterprise |
| Calidad de código | **SonarQube Community** | Quality gates en el pipeline |
| Escaneo de vulnerabilidades | **Trivy** | Integrado en Harbor + stage explícito en Jenkins |
| CNI Kubernetes | **Calico** | Aplica NetworkPolicies (Flannel no lo hace) |
| UI Ansible | **AWX** | RBAC + historial de ejecución, upstream gratuito de Ansible Tower |
| Estrategia de branches | **Trunk-based** | Main protegido, feature branches de vida corta, PR obligatorio |

> **Por qué dos capas de orquestación:** Los servicios personales (Jellyfin, \*arr, Nextcloud) son estables y no se benefician del scheduling, auto-healing ni rolling updates de K8s. Docker Compose es más sencillo de operar y depurar. K3s se reserva para el stack DevOps donde sí aporta valor real: despliegues declarativos, GitOps y operaciones Kubernetes demostrables.

### 8.2 Arquitectura por capas

```
┌────────────────────────────────────────────────────────────────┐
│                  CAPA GIT (Source of Truth)                    │
│                                                                │
│   Forgejo (privado)                GitHub / GitLab.com (público)│
│   ├── IaC (OpenTofu, Ansible)      ├── Proyectos personales     │
│   ├── Stacks Docker Compose        └── GitHub Actions / GL CI  │
│   ├── Manifiestos K8s + Helm values                            │
│   └── Secretos cifrados (SOPS+Age)                             │
└────────────────────────┬───────────────────────────────────────┘
                         │ Webhooks
         ┌───────────────┴───────────────┐
         ▼                               ▼
┌─────────────────┐           ┌──────────────────────┐
│  CI/CD INFRA    │           │  CI/CD APLICACIONES  │
│                 │           │                      │
│  Woodpecker CI  │           │  Jenkins (en K3s)    │
│  ├── tofu plan  │           │  ├── Tests unitarios  │
│  ├── tofu apply │           │  ├── Quality gate SQ  │
│  ├── ansible    │           │  ├── docker build     │
│  └── compose up │           │  ├── Trivy scan       │
└────────┬────────┘           │  └── push → Harbor   │
         │                   └──────────┬───────────┘
         ▼                              │
┌─────────────────┐           ┌──────────────────────┐
│  CAPA IaC       │           │  REGISTRY            │
│                 │           │                      │
│  OpenTofu       │           │  Harbor              │
│  └── Proxmox    │           │  ├── Auto-scan Trivy  │
│                 │           │  ├── Pull policies    │
│  Ansible        │           │  └── Reglas retención │
│  └── Nodos K3s  │           └──────────┬───────────┘
│  └── Docker     │                      │ ArgoCD pull
│  └── Hardening  │                      ▼
└────────┬────────┘          ┌──────────────────────┐
         │                  │  CAPA GITOPS          │
         ▼                  │                       │
┌─────────────────┐         │  ArgoCD (en K3s)      │
│  ORQUESTACIÓN   │         │  └── App of Apps      │
│                 │         │  └── Auto-sync        │
│  Clúster K3s    │◄────────│  └── Git = verdad     │
│  ├── Jenkins    │         └──────────────────────┘
│  ├── ArgoCD     │
│  ├── SonarQube  │         ┌──────────────────────┐
│  ├── Vault      │         │  CAPA DE SECRETOS    │
│  └── Apps       │◄────────│                       │
│                 │         │  SOPS+Age (Git)        │
│  Docker Compose │         │  Vault (runtime K8s)   │
│  ├── Stack *arr │         └──────────────────────┘
│  ├── Jellyfin   │
│  ├── Nextcloud  │
│  └── Immich     │
└─────────────────┘
```

### 8.3 Pipelines CI/CD

#### Pipeline de infraestructura (Woodpecker CI)

Cada push a Forgejo ejecuta:

```
push a Forgejo
        │
        ▼
Woodpecker CI
    ├── lint        yamllint + docker compose config + ansible-lint
    ├── validate    SOPS decrypt en memoria + validación de esquema
    ├── plan        OpenTofu fmt + validate + plan (PRs con cambios en infrastructure/)
    └── deploy      webhook Portainer → actualización rolling del stack
```

#### Pipeline de aplicaciones (Jenkins + ArgoCD)

```
push a Forgejo
        │
        ▼
Jenkins (K3s)
    ├── test        tests unitarios
    ├── quality     quality gate SonarQube — falla en CRITICAL
    ├── build       docker build
    ├── scan        Trivy — falla en CVE CRITICAL
    ├── push        docker push → Harbor
    └── manifest    actualiza manifiesto K8s en Forgejo
                          │
                          ▼
                     ArgoCD (K3s)
                          │ detecta diff con Git
                          ▼
                     K3s rolling update
```

### 8.4 Arquitectura del Clúster K3s

K3s corre en VMs dedicadas en Proxmox (no en LXCs — K3s requiere acceso a módulos de kernel que los LXCs restringen por defecto):

```
┌──────────────────────────────────────────────────────────┐
│                      Clúster K3s                          │
│                                                          │
│  ┌──────────────────────┐   ┌──────────────────────┐    │
│  │   Control Plane      │   │    Worker Node        │    │
│  │   VM en pve-main     │   │    VM en pve-aux      │    │
│  │   VLAN 30 (SRV)      │   │    VLAN 30 (SRV)      │    │
│  │                      │   │                       │    │
│  │  • kube-apiserver    │   │  • Jenkins            │    │
│  │  • etcd (SQLite)     │   │  • ArgoCD             │    │
│  │  • kube-scheduler    │   │  • SonarQube          │    │
│  │  • controller-mgr    │   │  • HashiCorp Vault     │    │
│  │                      │   │  • AWX                │    │
│  └──────────────────────┘   └──────────────────────┘    │
│                                                          │
│  CNI:       Calico (aplicación de NetworkPolicies)        │
│  Ingress:   Traefik (por defecto en K3s)                  │
│  Storage:   NFS Subdir Provisioner → nas-01/tank          │
│  TLS:       cert-manager                                  │
└──────────────────────────────────────────────────────────┘
```

**Estrategia de namespaces:**

```
devops/       ← Jenkins, SonarQube, Harbor
platform/     ← ArgoCD, cert-manager
vault/        ← HashiCorp Vault
monitoring/   ← Prometheus, Grafana, Loki (Phase 8)
database/     ← PostgreSQL (compartido, una BD por servicio)
apps/         ← aplicaciones propias desplegadas por el pipeline
awx/          ← AWX (upstream de Ansible Tower)
```

**Por qué Calico en lugar de Flannel (CNI por defecto de K3s):** Flannel no aplica Kubernetes NetworkPolicies — las define pero las ignora. Calico sí las aplica. Para un stack DevOps profesional, el aislamiento de namespaces es necesario: Jenkins no debería alcanzar Vault directamente, SonarQube no debería alcanzar la BD de otro servicio. La API de NetworkPolicy es agnóstica al CNI, por lo que las habilidades aplican directamente a EKS/AKS con Calico o Cilium.

### 8.5 Estructura del Repositorio

```
.
├── infrastructure/
│   ├── opentofu/
│   │   ├── proxmox/        ← Definiciones de LXCs y VMs
│   │   └── k3s/            ← VMs nodos K3s (Phase 4+)
│   ├── ansible/
│   │   ├── inventory/
│   │   ├── group_vars/
│   │   ├── playbooks/
│   │   └── roles/
│   └── helm/               ← Values Helm para el stack K3s
│       ├── argocd/
│       ├── jenkins/
│       ├── sonarqube/
│       ├── vault/
│       ├── postgresql/
│       └── awx/
├── services/
│   ├── docker-compose/     ← Servicios personales (stacks Compose)
│   │   ├── media/
│   │   ├── core/
│   │   ├── monitoring/
│   │   ├── cloud/
│   │   └── devops/
│   └── k8s/                ← Workloads K3s (Phase 4+)
│       ├── argocd/apps/    ← Patrón App of Apps
│       ├── apps/
│       └── namespaces/     ← RBAC + NetworkPolicies
└── .woodpecker/            ← Definiciones de pipelines CI/CD
    ├── lint.yml
    ├── tofu-plan.yml
    └── deploy.yml
```

### 8.6 Gestión de Secretos

Todos los secretos siguen un modelo por capas:

| Capa | Herramienta | Cuándo |
|---|---|---|
| Git / Docker Compose | **SOPS + Age** | Secretos estáticos commiteados a Git — cifrados antes del commit |
| K8s / Pods K3s | **HashiCorp Vault** | Secretos dinámicos en runtime — inyectados por Vault Agent |
| Pipelines | **Secretos Woodpecker / Credentials Jenkins** | Credenciales de pipelines CI/CD |

```bash
# Editar un archivo cifrado
sops services/docker-compose/devops/woodpecker-ci/.env.enc

# Verificar siempre antes de commitear
git diff --staged | grep -iE "(password|key|token|secret)"
```

**Reglas:**
- Nunca commitear archivos `.env` con valores reales
- Nunca commitear claves SSH, claves Age, tokens o contraseñas en texto plano
- `.env.example` con nombres de variables (sin valores) se commitea en su lugar
- Sin secretos estáticos en manifiestos K8s — Vault Agent los inyecta al arrancar el pod

### 8.7 Roadmap

| Fase | Descripción | Estado |
|---|---|---|
| **Phase 0** | Workstation, tooling, init del repo, SOPS + Age | ✅ Completada |
| **Phase 1** | Red: OPNsense, 7 VLANs, switch gestionado, Tailscale | ✅ Completada |
| **Phase 1.5** | VPN: Tailscale (remoto) + ProtonVPN WireGuard (salida) | ✅ Completada |
| **Phase 2** | TrueNAS, pools ZFS, stack \*arr, qBittorrent, PBS, Syncthing | ✅ Completada |
| **Phase 3** | Clúster Proxmox 3 nodos, LXCs Docker, Portainer multi-host | ✅ Completada |
| **Phase 4** | DevOps Core: Forgejo, Woodpecker CI, Harbor + Trivy, pipelines IaC | 🔄 En curso |
| **Phase 4+** | DevOps Enterprise: K3s, Jenkins, ArgoCD, SonarQube, Vault, AWX | ⏳ Planificada |
| **Phase 5** | NGINX Proxy Manager, Authentik SSO, SSL, Vaultwarden | ⏳ Planificada |
| **Phase 6** | Nextcloud, Immich, Paperless-ngx | ⏳ Planificada |
| **Phase 7** | Jellyfin, Overseerr | ⏳ Planificada |
| **Phase 8** | Prometheus, Grafana, Loki, Alertmanager, Uptime Kuma | ⏳ Planificada |
| **Phase 9** | Agente IA OpenClaw | ⏳ Planificada |
