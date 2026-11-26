# LXC con Docker. Importados del clúster (imports.tf): el código describe lo que ya hay.
#
# Lo que la API con token no puede gestionar se ignora:
# - Las líneas lxc.* en crudo del .conf (apparmor unconfined, devices.allow, cap.drop y,
#   en docker-main, el bind mount de git-storage) no existen en el provider: solo
#   root@pam con contraseña puede escribirlas. Viven fuera de OpenTofu (runbook).
# - `unprivileged` y `features` fuerzan recrear el contenedor; un cambio aquí sería
#   destruir y crear, nunca un ajuste en caliente.

resource "proxmox_virtual_environment_container" "docker_main" {
  node_name     = "pve-main"
  vm_id         = 200
  unprivileged  = false # riesgo conocido: pasar a no privilegiado o a VM (proyecto Terraform Proxmox)
  start_on_boot = true

  console {
    enabled   = true
    tty_count = 2
    type      = "tty"
  }

  cpu {
    cores = 4
  }

  memory {
    dedicated = 4096
    swap      = 0
  }

  disk {
    datastore_id = "local-lvm"
    size         = 40
  }

  features {
    keyctl = true
  }

  initialization {
    hostname = "docker-main"

    dns {
      domain  = "home.arpa"
      servers = ["10.0.30.1"]
    }

    ip_config {
      ipv4 {
        address = "10.0.30.20/24"
        gateway = "10.0.30.1"
      }
    }
  }

  network_interface {
    name        = "eth0"
    bridge      = "vmbr0"
    vlan_id     = 30
    firewall    = true
    mac_address = "BC:24:11:76:54:06"
  }

  operating_system {
    template_file_id = "nas-images:vztmpl/debian-13-standard_13.1-2_amd64.tar.zst" # solo se usa al recrear (ignore_changes)
    type             = "debian"
  }

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [operating_system[0].template_file_id]
  }
}

resource "proxmox_virtual_environment_container" "docker_aux" {
  node_name     = "pve-aux"
  vm_id         = 201
  unprivileged  = true
  start_on_boot = true

  console {
    enabled   = true
    tty_count = 2
    type      = "tty"
  }

  cpu {
    cores = 4
  }

  memory {
    # 4 GB: con todo el stack de monitorización gasta ~1 GB (2026-11-25); antes 9216
    dedicated = 4096
    swap      = 0
  }

  disk {
    datastore_id = "local-lvm"
    size         = 60
  }

  features {
    keyctl = true
  }

  initialization {
    hostname = "docker-aux"

    dns {
      domain  = "home.arpa"
      servers = ["10.0.30.1"]
    }

    ip_config {
      ipv4 {
        address = "10.0.30.21/24"
        gateway = "10.0.30.1"
      }
    }
  }

  network_interface {
    name        = "eth0"
    bridge      = "vmbr0"
    vlan_id     = 30
    firewall    = true
    mac_address = "BC:24:11:C7:A4:0B"
  }

  operating_system {
    template_file_id = "nas-images:vztmpl/debian-13-standard_13.1-2_amd64.tar.zst" # solo se usa al recrear (ignore_changes)
    type             = "debian"
  }

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [operating_system[0].template_file_id]
  }
}
