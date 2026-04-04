# Homelab Infrastructure

Personal homelab managed entirely as Infrastructure as Code. Two parallel objectives: a private self-hosted stack that replaces cloud services, and a production-grade DevOps pipeline built with the same tools used in enterprise environments.

**Version:** 3.2 — March 2026
**Status:** Phase 4 in progress

---

## Table of Contents

1. [Phase History](#1-phase-history)
2. [Hardware](#2-hardware)
3. [Network & Infrastructure](#3-network--infrastructure)
4. [Services](#4-services)
5. [Virtualization](#5-virtualization)
6. [Storage](#6-storage)
7. [Remote Access](#7-remote-access)
8. [DevOps & IaC](#8-devops--iac)

---

## 1. Phase History

### Phase 1 — Network (✅ Done)

| Aspect | Before | After |
|---|---|---|
| Network topology | Theoretical | Dual-switch implemented (ISP router + managed switch) |
| VLANs | Concept | 7 VLANs operational with per-VLAN egress policies |
| DHCP | Generic | Dnsmasq per-VLAN with static reservations |
| Remote VPN | WireGuard (planned) | Tailscale implemented — works with CGNAT, no open ports required |
| Firewall rules | Theoretical | Implemented with inter-VLAN isolation and selective access |

### Phase 2 — Storage & Media (✅ Done)

| Aspect | After |
|---|---|
| NAS | TrueNAS Scale on Dell R230 |
| Storage | ZFS pools: `tank` (HDD stripe) + `vault` (SSD mirror) |
| Media stack | Sonarr, Radarr, Lidarr, Prowlarr, Bazarr, qBittorrent, Calibre-Web Automated — all operational |
| Backup | Proxmox Backup Server (PBS) in Docker on NAS |
| Sync | Syncthing for mobile device sync |

### Phase 3 — Cluster & Container Management (✅ Done)

| Aspect | Before | After |
|---|---|---|
| Proxmox | Single node | **3-node cluster: pve-router + pve-main + pve-aux** |
| docker-main | Did not exist | LXC Debian 12, VLAN 30, 10GB RAM |
| docker-aux | Did not exist | LXC Debian 12, VLAN 30, 9GB RAM |
| Macvlan networking | NAS only | All 3 Docker hosts with non-overlapping ranges |
| Portainer | Did not exist | Server on docker-main + Agents on aux and nas |
| NFS cluster storage | NAS only | `tank/vms/images` mounted on pve-main and pve-aux |

---

## 2. Hardware

### Production nodes (24/7)

| ID | Device | Specs | Role |
|---|---|---|---|
| HW-SRV-01 | Dell R230 | 16GB RAM, 6TB HDD, 800GB SSD | NAS / TrueNAS Scale |
| HW-SRV-02 | Mini PC (quad-NIC) | 20GB RAM | Proxmox router + OPNsense VM |
| HW-SRV-03 | Mini PC | 16GB RAM, 256GB SSD, 1TB HDD | Proxmox primary node |
| HW-SRV-04 | Mini PC | 10GB RAM | Proxmox secondary node |
| HW-IOT-01 | Raspberry Pi 4 | 4GB RAM | DNS failover / utilities |

All production nodes run 24/7. Total idle power draw is under 100W.

### Workstations

| ID | Device | Specs | Role |
|---|---|---|---|
| HW-WKS-01 | Desktop PC | 32GB DDR5, Ryzen 7 9700X | Primary workstation |
| HW-WKS-02 | Desktop PC | 32GB DDR4, i7-7700K | Secondary / dev workstation |

---

## 3. Network & Infrastructure

### 3.1 Dual-switch topology

#### Switch 1: ISP Router

- No VLANs, manages `192.168.1.0/24`
- Connects: Internet ↔ Proxmox management + OPNsense WAN
- **Rationale:** Proxmox management here = always reachable regardless of OPNsense state

#### Switch 2: TP-Link TL-SG108E (managed)

- 802.1Q VLANs, manages `10.0.x.0/24`
- Connects: OPNsense ↔ all physical hardware on VLAN 5
- **Rationale:** Physical hardware here = independent of OPNsense

```
                      INTERNET
                          │
                   ISP Router (192.168.1.0/24)
                   └─ Proxmox management (em0)
                   └─ OPNsense WAN (igb0, DHCP)
                          │
                  HW-SRV-02 (pve-router)
                          │
                igb3 → TL-SG108E (VLAN aware)
                          │
         ┌────────────────┼──────────────────┐
      VLAN 5           VLAN 10            VLAN 30
      (INFRA)          (MGMT)             (SRV)
    bare metal      virtualized          services
    nas-01          fw-01                docker-main
    pve-main        prx-01               docker-aux
    pve-aux         auth-01              K3s (planned)
    wks-01/02
    rpi-dns
```

### 3.2 VLAN segmentation

| VLAN | Name | Subnet | Egress | Purpose |
|---|---|---|---|---|
| 5 | INFRA | 10.0.5.0/24 | Direct ISP | Physical hardware: Proxmox, TrueNAS, IPMI, RPi |
| 10 | MGMT | 10.0.10.0/24 | Direct ISP | Virtualized services: OPNsense, NGINX, Authentik |
| 15 | AI | 10.0.15.0/24 | Direct ISP | AI agents (OpenClaw) — strict firewall |
| 20 | DEVICES | 10.0.20.0/24 | ProtonVPN | Personal devices |
| 30 | SRV | 10.0.30.0/24 | ProtonVPN + kill switch | Docker stacks, K3s workloads |
| 50 | IOT | 10.0.50.0/24 | ProtonVPN | Untrusted IoT — internet only |
| 99 | GUEST | 10.0.99.0/24 | ProtonVPN | Guests — internet only |

**Critical separation: INFRA vs MGMT**

- **VLAN 5 (INFRA):** Physical layer. Hardware on managed switch. ✅ Works even if OPNsense is down.
- **VLAN 10 (MGMT):** Virtualized layer. Services in VMs. ❌ Falls if OPNsense fails. But ✅ INFRA remains accessible.

### 3.3 Switch port configuration (TL-SG108E)

| VLAN | P1 | P2 | P3 | P4 | P6 | Description |
|---|---|---|---|---|---|---|
| 5 (INFRA) | T | U | U | U | U | Physical hardware |
| 10 (MGMT) | T | - | - | - | - | Virtualized services |
| 15 (AI) | T | - | - | - | - | AI VLAN isolated |
| 30 (SRV) | T | - | - | - | **T** | Services — **P6 Tagged required for NAS containers** |
| 50 (IOT) | T | - | - | - | - | IoT isolated |

> **P6 VLAN 30 Tagged:** Required so Docker containers on the NAS with macvlan `srv-net` addresses are reachable from outside the NAS. Without this, VLAN 30 traffic stays confined to the NAS.

**Legend:** T=Tagged, U=Untagged, -=Not Member

| Port | Device | VLAN | Role |
|---|---|---|---|
| P1 | pve-router igb3 | Trunk (all VLANs tagged) | OPNsense router trunk |
| P2 | pve-aux | INFRA (5), untagged | Proxmox node |
| P3 | wks-02 | INFRA (5), untagged | Dev workstation |
| P4 | pve-main | INFRA (5), untagged | Proxmox node |
| P6 | nas-01 | INFRA (5) untagged + SRV (30) tagged | NAS |
| P8 | wks-01 | INFRA (5), untagged | Primary workstation |

### 3.4 DHCP ranges per VLAN (Dnsmasq on OPNsense)

| VLAN | Dynamic range | Static reservations |
|---|---|---|
| 5 (INFRA) | .100–.200 | nas-01, pve-main, pve-aux, wks-01, wks-02, rpi-dns |
| 10 (MGMT) | .100–.200 | OPNsense, NGINX, Authentik |
| 30 (SRV) | .100–.254 | `.10–.57` reserved for macvlan containers |
| 50 (IOT) | .100–.200 | — |

### 3.5 Macvlan address ranges (VLAN 30 — no overlap)

| Host | Interface | Assigned range |
|---|---|---|
| docker-nas (nas-01) | eno1.30 | 10.0.30.10–.25 |
| docker-main (LXC pve-main) | eth0 | 10.0.30.26–.41 |
| docker-aux (LXC pve-aux) | eth0 | 10.0.30.42–.57 |
| DHCP dynamic | — | 10.0.30.100+ |

### 3.6 Firewall rules (OPNsense) — key policies

```
INFRA → can reach: INFRA, MGMT, SRV, internet
MGMT  → can reach: INFRA, SRV, internet
SRV   → can reach: SRV (intra), internet via ProtonVPN (kill switch active)
IOT   → can reach: internet only (ProtonVPN)
AI    → can reach: internet (restricted), no access to other VLANs
```

---

## 4. Services

### Nomenclature

```
Format: [category]-[function]-[instance]

Categories:
  fw   = Firewall/Router      prx  = Proxy
  dns  = DNS                  auth = Authentication
  mon  = Monitoring           nas  = Storage
  media = Multimedia          arr  = Content management
  dev  = Development          ai   = Artificial Intelligence
  app  = Applications         bkp  = Backup
```

### 4.1 Physical Infrastructure (VLAN 5 — INFRA)

| ID | Service | Host | Type | Function |
|---|---|---|---|---|
| infra-pve-01 | Proxmox VE | pve-router | Bare Metal | Hypervisor + OPNsense host |
| infra-pve-02 | Proxmox VE | pve-main | Bare Metal | Primary hypervisor |
| infra-pve-03 | Proxmox VE | pve-aux | Bare Metal | Secondary hypervisor |
| infra-nas-01 | TrueNAS Scale | nas-01 | Bare Metal | NAS — ZFS, NFS, Docker |
| infra-ipmi-01 | iDRAC/IPMI | nas-01 | Firmware | Dell hardware management |
| infra-rpi-01 | Raspberry Pi | rpi-dns | Bare Metal | DNS failover + utilities |

### 4.2 Management (VLAN 10 — MGMT)

| ID | Service | Host | Type | Port | Function |
|---|---|---|---|---|---|
| fw-opnsense-01 | OPNsense | pve-router | VM | 443 | **Firewall, NAT, DHCP, VLANs, Tailscale** |
| prx-nginx-01 | NGINX Proxy Manager | pve-router | LXC | 81 | Reverse proxy + SSL Let's Encrypt |
| auth-authentik-01 | Authentik | pve-router | LXC | 9000 | SSO / Identity Provider |

### 4.3 DNS

| ID | Service | Host | Function |
|---|---|---|---|
| dns-unbound-01 | Unbound (OPNsense integrated) | fw-01 | Recursive resolver + DNSSEC + split-horizon |
| dns-rpi-01 | Unbound backup | rpi-dns | DNS failover (future) |

> **Design decision:** Unbound integrated in OPNsense instead of AdGuard Home. Rationale: no additional services to maintain, native DNSSEC and split-horizon support for `.homelab` domain.

### 4.4 Monitoring (VLAN 30 — SRV)

> Phase 8 — planned on `docker-aux`, macvlan range `.42–.57`

| ID | Service | Host | Port | Function |
|---|---|---|---|---|
| mon-prometheus-01 | Prometheus | docker-aux | 9090 | Metrics database + alerting |
| mon-grafana-01 | Grafana | docker-aux | 3001 | Dashboards — DORA metrics, infra health |
| mon-loki-01 | Loki | docker-aux | 3100 | Centralized log aggregation |
| mon-uptime-01 | Uptime Kuma | docker-aux | 3002 | Service availability monitoring |
| mon-speedtest-01 | Speedtest Tracker | docker-aux | 8765 | Automated speed tests |
| mon-homepage-01 | Homepage | docker-aux | 3003 | Landing dashboard |
| mon-nodeexp-01 | Node Exporter | All hosts | 9100 | CPU, RAM, disk metrics |
| mon-ipmi-01 | IPMI Exporter | docker-aux | 9290 | Dell hardware metrics |

### 4.5 Storage (VLAN 30 — SRV)

| ID | Service | Host | Type | Function |
|---|---|---|---|---|
| app-nextcloud-01 | Nextcloud | docker-main | Docker | Personal cloud: files, calendar, contacts |
| app-immich-01 | Immich | docker-main | Docker | Photo/video management (Google Photos alternative) |
| app-syncthing-01 | Syncthing | docker-nas | Docker macvlan | ✅ P2P file sync to mobile devices |
| app-paperless-01 | Paperless-ngx | docker-main | Docker | Document management with OCR |

### 4.6 Media (VLAN 30 — SRV)

> Jellyfin and Overseerr planned for Phase 7 on `docker-main`.

| ID | Service | Host | Type | Port | Status | Function |
|---|---|---|---|---|---|---|
| media-jellyfin-01 | Jellyfin | docker-main | Docker macvlan | 8096 | ⏳ Phase 7 | Media streaming server |
| media-overseerr-01 | Overseerr | docker-main | Docker macvlan | 5055 | ⏳ Phase 7 | Media request portal |
| arr-sonarr-01 | Sonarr | docker-nas | Docker macvlan | 8989 | ✅ Operational | Automatic TV series management |
| arr-radarr-01 | Radarr | docker-nas | Docker macvlan | 7878 | ✅ Operational | Automatic movie management |
| arr-lidarr-01 | Lidarr | docker-nas | Docker macvlan | 8686 | ✅ Operational | Automatic music management |
| arr-prowlarr-01 | Prowlarr | docker-nas | Docker macvlan | 9696 | ✅ Operational | Centralized indexer manager |
| arr-bazarr-01 | Bazarr | docker-nas | Docker macvlan | 6767 | ✅ Operational | Automatic subtitle downloads |
| media-qbittorrent-01 | qBittorrent | docker-nas | Docker macvlan | 8080 | ✅ Operational | Web download client (routed through ProtonVPN) |
| media-cwa-01 | Calibre-Web Automated | docker-nas | Docker macvlan | 8083 | ✅ Operational | Ebook library with automatic ingestion and format conversion |

### 4.7 DevOps (VLAN 30 — SRV)

| ID | Service | Host | Type | Port | Status | Function |
|---|---|---|---|---|---|---|
| dev-portainer-01 | Portainer | docker-main | Docker macvlan | 9443 | ✅ Operational | Multi-host container management UI |
| dev-forgejo-01 | Forgejo | docker-main | Docker macvlan | 3000 | 🔄 Phase 4 | Self-hosted Git server |
| dev-woodpecker-01 | Woodpecker CI | docker-main | Docker macvlan | 8000 | 🔄 Phase 4 | CI/CD pipelines |
| dev-harbor-01 | Harbor | docker-main | Docker (LXC IP) | 80/443 | 🔄 Phase 4 | Private container registry |
| dev-jenkins-01 | Jenkins | K3s worker | Helm | 8080 | ⏳ Phase 4+ | Application CI/CD pipelines |
| dev-argocd-01 | ArgoCD | K3s worker | Helm | 443 | ⏳ Phase 4+ | GitOps continuous delivery |
| dev-sonarqube-01 | SonarQube | K3s worker | Helm | 9000 | ⏳ Phase 4+ | Code quality gate |
| dev-vault-01 | HashiCorp Vault | K3s worker | Helm | 8200 | ⏳ Phase 4+ | Dynamic secrets management |
| dev-awx-01 | AWX | K3s worker | Operator | 80 | ⏳ Phase 4+ | Ansible automation UI |

### 4.8 AI (VLAN 15 — AI)

| ID | Service | Host | Type | Port | Status | Function |
|---|---|---|---|---|---|---|
| ai-openclaw-01 | OpenClaw | pve-router | LXC | 18789 | ⏳ Phase 9 | AI agent for homelab automation |

### 4.9 Backup

| ID | Service | Host | Type | Port | Status | Function |
|---|---|---|---|---|---|---|
| bkp-pbs-01 | Proxmox Backup Server | nas-01 | Docker | 8007 | ✅ Operational | VM/LXC backups to NAS |

**Total: 35+ services across 3 Docker hosts + NAS + 3 Proxmox nodes + OPNsense**

---

## 5. Virtualization

### 5.1 Proxmox Cluster (3 nodes)

| Node | Hardware | RAM | Role |
|---|---|---|---|
| pve-router | Mini PC (quad-NIC) | 20GB | Router + management services |
| pve-main | Mini PC | 16GB | Core Docker workloads, K3s control plane |
| pve-aux | Mini PC | 10GB | Aux services, K3s worker |

### 5.2 Workload distribution

**pve-router (20GB)**
- `fw-opnsense-01` (VM, 4GB) — OPNsense firewall
- `prx-nginx-01` (LXC, 512MB) — Reverse proxy *(Phase 5)*
- `auth-authentik-01` (LXC, 1GB) — SSO *(Phase 5)*
- `ai-openclaw-01` (LXC, 4GB) — AI agent *(Phase 9)*

**pve-main (16GB)**
- `docker-main` (LXC, 10GB) ✅ — Portainer, Forgejo, Woodpecker, Harbor

**pve-aux (10GB)**
- `docker-aux` (LXC, 6GB after Phase 4+) ✅ — Monitoring, cloud services
- K3s worker VM (3GB) — DevOps stack *(Phase 4+)*

### 5.3 VM vs LXC decision

| Workload type | Use | Reason |
|---|---|---|
| OPNsense | VM | Needs own kernel |
| K3s nodes | VM | Requires kernel modules (ip_tables, nf_conntrack, br_netfilter) that LXCs restrict |
| Everything else | LXC | Saves ~600MB RAM idle per instance |

### 5.4 LXC configuration for Docker

```ini
# /etc/pve/lxc/<CTID>.conf — required before first start
lxc.apparmor.profile: unconfined
lxc.cgroup2.devices.allow: a
lxc.cap.drop:
features: keyctl=1
```

> **Warning:** Do NOT add `nesting=1` alongside `apparmor: unconfined` — they conflict and the LXC will fail to start.

---

## 6. Storage

### 6.1 ZFS Pools

| Pool | Disks | Capacity | Layout | Purpose |
|---|---|---|---|---|
| `tank` | 2x HDD 3TB | ~6TB | Stripe | High-volume, replaceable data |
| `vault` | 2x SSD 800GB | ~400GB usable | Mirror RAID-1 | Critical data: fast and redundant |

### 6.2 Dataset structure

```
tank  (~6TB — HDD stripe)
├── backups/
│   ├── proxmox/      ← PBS backup datastore
│   ├── databases/
│   └── configs/
├── downloads/
│   ├── complete/
│   └── incomplete/
├── media/
│   ├── movies/ tv/ music/
│   └── isos/
└── vms/
    └── images/       ← Proxmox cluster NFS storage

vault  (~400GB — SSD mirror)
├── apps/             ← Container appdata (NFS → docker hosts)
├── docker/           ← Docker daemon data-root (NFS → docker hosts)
├── documents/        ← Personal documents (NFS + SMB)
├── git-storage/      ← Forgejo repositories
└── secrets/          ← Age keys, SSH keys, certs
```

### 6.3 NFS Shares

| Share | Path | Access | Notes |
|---|---|---|---|
| media | /tank/media | VLAN 30, INFRA | Jellyfin, \*arr |
| downloads | /tank/downloads | VLAN 30 | qBittorrent, staging |
| backups | /tank/backups | VLAN 5 only | PBS and Restic only |
| vms | /tank/vms | VLAN 5 | Proxmox cluster shared storage |
| vault/apps | /vault/apps | VLAN 30 | Docker appdata (SSD) |
| vault/docker | /vault/docker | VLAN 30 | Docker data-root (SSD) |
| vault/git-storage | /vault/git-storage | VLAN 30, INFRA | Forgejo repos |

---

## 7. Remote Access

**Tailscale** runs as a subnet router plugin inside OPNsense, advertising the full `10.0.0.0/8` range. This provides access to all VLANs and services from any device with a Tailscale client.

**Why Tailscale and not traditional WireGuard:** The ISP uses CGNAT with no public IPv4 address. Traditional WireGuard requires a public endpoint to receive connections, which is impossible under CGNAT. Tailscale uses its coordination server to establish peer-to-peer tunnels through NAT traversal — no open ports needed on the ISP router.

Tailscale clients: primary workstation, mobile devices.

---

## 8. DevOps & IaC

### 8.1 Philosophy & Architecture Decisions

The DevOps stack replicates a real enterprise environment using exclusively open-source, free tools. Each tool has a direct corporate equivalent, allowing demonstration of practical experience in interviews without having worked in a DevOps company.

| Decision | Choice | Reason |
|---|---|---|
| Private Git (IaC, configs) | **Forgejo** | Lightweight, self-hosted, <200MB RAM |
| Public Git (projects, CV) | **GitHub / GitLab.com** | Visibility, free Actions/CI |
| CI/CD infrastructure | **Woodpecker CI** | Forgejo-native webhooks, YAML identical to GitHub Actions |
| CI/CD applications | **Jenkins** | De facto standard in Spanish enterprises, especially banking |
| Container registry | **Harbor** | CNCF standard, Trivy integrated, project-level policies |
| Orchestration (DevOps stack) | **K3s** | Same API as EKS/AKS/GKE, ~512MB idle |
| Orchestration (personal services) | **Docker Compose** | Stable services don't need K8s scheduling or rolling updates |
| GitOps | **ArgoCD** | Pull-based, declarative, used directly in enterprise production |
| IaC provisioning | **OpenTofu** | Open-source fork of Terraform, 100% HCL compatible, MPL-2.0 license |
| IaC configuration | **Ansible + AWX** | Industry standard, same in homelab as in enterprises |
| K8s package manager | **Helm** | Standard for deploying applications on Kubernetes |
| Secrets in Git | **SOPS + Age** | File encryption before commit, already operational |
| Secrets in K8s | **HashiCorp Vault** | Dynamic secrets, auto-rotation, enterprise standard |
| Code quality | **SonarQube Community** | Quality gates in pipeline |
| Vulnerability scanning | **Trivy** | Integrated in Harbor + explicit Jenkins stage |
| Kubernetes CNI | **Calico** | Enforces NetworkPolicies (Flannel does not) |
| Ansible UI | **AWX** | RBAC + execution history, free upstream of Ansible Tower |
| Branch strategy | **Trunk-based** | Protected main, short-lived feature branches, PR required |

> **Why two orchestration layers:** Personal services (Jellyfin, \*arr, Nextcloud) are stable and don't benefit from K8s scheduling, auto-healing, or rolling updates. Docker Compose is simpler to operate and debug. K3s is reserved for the DevOps stack where it adds real value: declarative deployments, GitOps, and demonstrable Kubernetes operations.

### 8.2 Layer Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                     GIT LAYER (Source of Truth)                │
│                                                                │
│   Forgejo (private)               GitHub / GitLab.com (public) │
│   ├── IaC (OpenTofu, Ansible)     ├── Personal projects        │
│   ├── Docker Compose stacks       └── GitHub Actions / GL CI   │
│   ├── K8s manifests + Helm values                              │
│   └── Encrypted secrets (SOPS+Age)                            │
└────────────────────────┬───────────────────────────────────────┘
                         │ Webhooks
         ┌───────────────┴───────────────┐
         ▼                               ▼
┌─────────────────┐           ┌──────────────────────┐
│  CI/CD INFRA    │           │  CI/CD APPLICATIONS  │
│                 │           │                      │
│  Woodpecker CI  │           │  Jenkins (on K3s)    │
│  ├── tofu plan  │           │  ├── Unit tests       │
│  ├── tofu apply │           │  ├── SonarQube gate   │
│  ├── ansible    │           │  ├── docker build     │
│  └── compose up │           │  ├── Trivy scan       │
└────────┬────────┘           │  └── push → Harbor   │
         │                   └──────────┬───────────┘
         ▼                              │
┌─────────────────┐           ┌──────────────────────┐
│  IaC LAYER      │           │  REGISTRY            │
│                 │           │                      │
│  OpenTofu       │           │  Harbor              │
│  └── Proxmox    │           │  ├── Trivy auto-scan  │
│                 │           │  ├── Pull policies    │
│  Ansible        │           │  └── Retention rules  │
│  └── K3s nodes  │           └──────────┬───────────┘
│  └── Docker     │                      │ ArgoCD pull
│  └── Hardening  │                      ▼
└────────┬────────┘          ┌──────────────────────┐
         │                  │  GITOPS LAYER         │
         ▼                  │                       │
┌─────────────────┐         │  ArgoCD (on K3s)      │
│  ORCHESTRATION  │         │  └── App of Apps      │
│                 │         │  └── Auto-sync        │
│  K3s Cluster    │◄────────│  └── Git = truth      │
│  ├── Jenkins    │         └──────────────────────┘
│  ├── ArgoCD     │
│  ├── SonarQube  │         ┌──────────────────────┐
│  ├── Vault      │         │  SECRETS LAYER        │
│  └── Apps       │◄────────│                       │
│                 │         │  SOPS+Age (Git)        │
│  Docker Compose │         │  Vault (K8s runtime)   │
│  ├── *arr stack │         └──────────────────────┘
│  ├── Jellyfin   │
│  ├── Nextcloud  │
│  └── Immich     │
└─────────────────┘
```

### 8.3 CI/CD Pipelines

#### Infrastructure pipeline (Woodpecker CI)

Every push to Forgejo triggers:

```
push to Forgejo
        │
        ▼
Woodpecker CI
    ├── lint        yamllint + docker compose config + ansible-lint
    ├── validate    SOPS decrypt in-memory + schema check
    ├── plan        OpenTofu fmt + validate + plan (PRs touching infrastructure/)
    └── deploy      Portainer webhook → rolling stack update
```

#### Application pipeline (Jenkins + ArgoCD)

```
push to Forgejo
        │
        ▼
Jenkins (K3s)
    ├── test        unit tests
    ├── quality     SonarQube gate — fails on CRITICAL
    ├── build       docker build
    ├── scan        Trivy — fails on CVE CRITICAL
    ├── push        docker push → Harbor
    └── manifest    update K8s manifest commit in Forgejo
                          │
                          ▼
                     ArgoCD (K3s)
                          │ detects Git diff
                          ▼
                     K3s rolling update
```

### 8.4 K3s Cluster Architecture

K3s runs on dedicated VMs in Proxmox (not LXCs — K3s requires kernel module access that LXCs restrict by default):

```
┌──────────────────────────────────────────────────────────┐
│                      K3s Cluster                          │
│                                                          │
│  ┌──────────────────────┐   ┌──────────────────────┐    │
│  │   Control Plane      │   │    Worker Node        │    │
│  │   VM on pve-main     │   │    VM on pve-aux      │    │
│  │   VLAN 30 (SRV)      │   │    VLAN 30 (SRV)      │    │
│  │                      │   │                       │    │
│  │  • kube-apiserver    │   │  • Jenkins            │    │
│  │  • etcd (SQLite)     │   │  • ArgoCD             │    │
│  │  • kube-scheduler    │   │  • SonarQube          │    │
│  │  • controller-mgr    │   │  • HashiCorp Vault     │    │
│  │                      │   │  • AWX                │    │
│  └──────────────────────┘   └──────────────────────┘    │
│                                                          │
│  CNI:     Calico (NetworkPolicies enforcement)            │
│  Ingress: Traefik (default K3s)                          │
│  Storage: NFS Subdir Provisioner → nas-01/tank           │
│  TLS:     cert-manager                                   │
└──────────────────────────────────────────────────────────┘
```

**Namespace strategy:**

```
devops/       ← Jenkins, SonarQube, Harbor
platform/     ← ArgoCD, cert-manager
vault/        ← HashiCorp Vault
monitoring/   ← Prometheus, Grafana, Loki (Phase 8)
database/     ← PostgreSQL (shared, one DB per service)
apps/         ← own applications deployed through the pipeline
awx/          ← AWX (Ansible Tower upstream)
```

**Why Calico instead of Flannel (K3s default):** Flannel does not enforce Kubernetes NetworkPolicies — it defines them but ignores them. Calico enforces them. For a professional DevOps stack, namespace isolation is required: Jenkins shouldn't reach Vault directly, SonarQube shouldn't reach another service's database. The NetworkPolicy API is CNI-agnostic, so skills transfer directly to EKS/AKS with Calico or Cilium.

### 8.5 Repository Structure

```
.
├── infrastructure/
│   ├── opentofu/
│   │   ├── proxmox/        ← LXC and VM definitions
│   │   └── k3s/            ← K3s node VMs (Phase 4+)
│   ├── ansible/
│   │   ├── inventory/
│   │   ├── group_vars/
│   │   ├── playbooks/
│   │   └── roles/
│   └── helm/               ← Helm values for K3s stack
│       ├── argocd/
│       ├── jenkins/
│       ├── sonarqube/
│       ├── vault/
│       ├── postgresql/
│       └── awx/
├── services/
│   ├── docker-compose/     ← Personal services (Compose stacks)
│   │   ├── media/
│   │   ├── core/
│   │   ├── monitoring/
│   │   ├── cloud/
│   │   └── devops/
│   └── k8s/                ← K3s workloads (Phase 4+)
│       ├── argocd/apps/    ← App of Apps pattern
│       ├── apps/
│       └── namespaces/     ← RBAC + NetworkPolicies
└── .woodpecker/            ← CI/CD pipeline definitions
    ├── lint.yml
    ├── tofu-plan.yml
    └── deploy.yml
```

### 8.6 Secrets Management

All secrets follow a layered model:

| Layer | Tool | When |
|---|---|---|
| Git / Docker Compose | **SOPS + Age** | Static secrets committed to Git — encrypted before commit |
| K8s / K3s pods | **HashiCorp Vault** | Dynamic secrets at runtime — injected by Vault Agent |
| Pipelines | **Woodpecker secrets / Jenkins credentials** | CI/CD pipeline credentials |

```bash
# Edit an encrypted file
sops services/docker-compose/devops/woodpecker-ci/.env.enc

# Always verify before committing
git diff --staged | grep -iE "(password|key|token|secret)"
```

**Rules:**
- Never commit `.env` files with real values
- Never commit SSH keys, Age keys, tokens, or passwords in plaintext
- `.env.example` with variable names (no values) is committed instead
- No static secrets in K8s manifests — Vault Agent injects them at pod startup

### 8.7 Roadmap

| Phase | Description | Status |
|---|---|---|
| **Phase 0** | Workstation, tooling, repo init, SOPS + Age | ✅ Done |
| **Phase 1** | Network: OPNsense, 7 VLANs, managed switch, Tailscale | ✅ Done |
| **Phase 1.5** | VPN: Tailscale (remote) + ProtonVPN WireGuard (egress) | ✅ Done |
| **Phase 2** | TrueNAS, ZFS pools, \*arr stack, qBittorrent, Calibre-Web Automated, PBS, Syncthing | ✅ Done |
| **Phase 3** | Proxmox 3-node cluster, Docker LXCs, Portainer multi-host | ✅ Done |
| **Phase 4** | DevOps Core: Forgejo, Woodpecker CI, Harbor + Trivy, IaC pipelines | 🔄 In progress |
| **Phase 4+** | DevOps Enterprise: K3s, Jenkins, ArgoCD, SonarQube, Vault, AWX | ⏳ Planned |
| **Phase 5** | NGINX Proxy Manager, Authentik SSO, SSL, Vaultwarden | ⏳ Planned |
| **Phase 6** | Nextcloud, Immich, Paperless-ngx | ⏳ Planned |
| **Phase 7** | Jellyfin, Overseerr | ⏳ Planned |
| **Phase 8** | Prometheus, Grafana, Loki, Alertmanager, Uptime Kuma | ⏳ Planned |
| **Phase 9** | OpenClaw AI agent | ⏳ Planned |
