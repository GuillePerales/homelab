# VM de OPNsense (firewall y router de todo el homelab). Importada del clúster (imports.tf).
# Un apply aquí puede cortar la red entera: nunca reinicia sola tras un cambio
# (reboot_after_update = false) y no se puede destruir desde OpenTofu.

resource "proxmox_virtual_environment_vm" "fw_01" {
  name                = "fw-01"
  node_name           = "pve-router"
  vm_id               = 100
  on_boot             = true
  machine             = "q35"
  bios                = "seabios"
  scsi_hardware       = "virtio-scsi-single"
  boot_order          = ["sata0", "net0", "net1"]
  reboot_after_update = false

  cpu {
    cores   = 2
    sockets = 1
    type    = "host"
  }

  memory {
    dedicated = 4096
    floating  = 0 # balloon: 0
  }

  disk {
    datastore_id = "local-lvm"
    interface    = "sata0"
    size         = 16
    file_format  = "raw"
    aio          = "io_uring"
    cache        = "none"
  }

  cdrom {
    file_id   = "none"
    interface = "ide2"
  }

  # WAN
  network_device {
    bridge      = "vmbr1"
    model       = "virtio"
    mac_address = "BC:24:11:24:C3:45"
    firewall    = true
  }

  # LAN (trunk de VLANs)
  network_device {
    bridge      = "vmbr2"
    model       = "virtio"
    mac_address = "BC:24:11:21:30:EA"
    firewall    = true
  }

  operating_system {
    type = "other"
  }

  lifecycle {
    prevent_destroy = true
  }
}
