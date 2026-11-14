# El estado vive cifrado en el repo (terraform.tfstate, AES-GCM con clave derivada por
# PBKDF2). La frase llega por TF_VAR_state_passphrase: tofu.sh la descifra con SOPS de
# infrastructure/secrets/opentofu.yaml y el CI la lee de su secreto tofu_state_passphrase.
# Git no bloquea el estado: los apply solo desde el portátil, un único escritor.
variable "state_passphrase" {
  description = "Frase de cifrado del estado y los planes (infrastructure/secrets/opentofu.yaml)"
  type        = string
  sensitive   = true
}

terraform {
  encryption {
    key_provider "pbkdf2" "estado" {
      passphrase = var.state_passphrase
    }

    method "aes_gcm" "estado" {
      keys = key_provider.pbkdf2.estado
    }

    state {
      method   = method.aes_gcm.estado
      enforced = true
    }

    plan {
      method   = method.aes_gcm.estado
      enforced = true
    }
  }
}
