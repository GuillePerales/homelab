# VM del clúster K3s de un nodo (fase 4b). Se crea desde la plantilla cloud-init 9000
# (Debian 13 genericcloud, `debian-13-cloud`, hecha con qm en pve-main) y se puede apagar
# o destruir y recrear sin tocar nada más: los servicios del homelab siguen en Docker.
#
# La imagen genericcloud no trae qemu-guest-agent: el agente queda desactivado hasta que
# Ansible lo instale (si no, el provider espera a que la VM lo anuncie).

resource "proxmox_virtual_environment_vm" "k3s_01" {
  name      = "k3s-01"
  node_name = "pve-main"
  vm_id     = 300
  tags      = ["k3s"]
  on_boot   = false # laboratorio apagable: se arranca a mano
  # Sin reinicio al aplicar: un cambio de cloud-init reinició la VM el 2026-11-23 y
  # dejó Vault sellado. Los cambios que lo necesiten se aplican al reiniciar a mano.
  reboot_after_update = false
  machine             = "q35"
  bios                = "seabios"

  scsi_hardware = "virtio-scsi-single"
  boot_order    = ["scsi0"]

  clone {
    vm_id = 9000
    full  = true
  }

  agent {
    enabled = false
  }

  cpu {
    cores   = 2
    sockets = 1
    type    = "host" # host para los módulos de kernel que pide K3s
  }

  memory {
    dedicated = 4096
    floating  = 0 # sin balloon
  }

  disk {
    datastore_id = "local-lvm"
    interface    = "scsi0"
    size         = 32
    file_format  = "raw"
    discard      = "on"
    ssd          = true
    iothread     = true
  }

  network_device {
    bridge   = "vmbr0"
    model    = "virtio"
    vlan_id  = 30
    firewall = true
  }

  operating_system {
    type = "l26"
  }

  initialization {
    datastore_id = "local-lvm"

    dns {
      domain  = "home.arpa"
      servers = ["10.0.30.1"]
    }

    ip_config {
      ipv4 {
        address = "10.0.30.70/24" # fuera de los bloques macvlan y del DHCP .100-.200
        gateway = "10.0.30.1"
      }
    }

    user_account {
      username = "debian"
      keys     = [var.k3s_ssh_public_key]
    }
  }

  # La VM se enciende y se apaga a mano (laboratorio apagable): que OpenTofu no la arranque.
  lifecycle {
    ignore_changes = [started]
  }
}
