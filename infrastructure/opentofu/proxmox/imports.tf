# Recursos creados a mano antes de la IaC: se importan en lugar de crearse.
# Formato del ID en bpg/proxmox: <nodo>/<vmid>.
import {
  to = proxmox_virtual_environment_vm.fw_01
  id = "pve-router/100"
}

import {
  to = proxmox_virtual_environment_container.docker_main
  id = "pve-main/200"
}

import {
  to = proxmox_virtual_environment_container.docker_aux
  id = "pve-aux/201"
}
