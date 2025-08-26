packer {
  required_plugins {
    proxmox = {
      version = ">= 1.1.8"
      source  = "github.com/hashicorp/proxmox"
    }
  }
}

variable "proxmox_host" {
  type    = string
  default = "10.10.1.21:8006"
}

variable "proxmox_token" {
  type    = string
  default = "packer@pam!packer=caa32cfb-7745-49cc-9d01-42dcb0d9e42e"
}

variable "template_name" {
  type    = string
  default = "ubuntu-2404-golden"
}

variable "template_id" {
  type    = string
  default = "9001"
}

source "proxmox-clone" "ubuntu-cloud" {
  proxmox_url              = "https://${var.proxmox_host}/api2/json"
  username                = "packer@pam!packer"
  token                   = "caa32cfb-7745-49cc-9d01-42dcb0d9e42e"
  insecure_skip_tls_verify = true
  
  vm_name                 = var.template_name
  vm_id                   = var.template_id
  template_name           = var.template_name
  template_description    = "Ubuntu 24.04 Golden Image with qemu-guest-agent"
  
  node                    = "node1"
  cores                   = 2
  memory                  = 2048
  
  # Hardware configuration to match base template
  cpu_type                = "host"
  os                      = "l26"
  scsi_controller         = "virtio-scsi-pci"
  
  # Clone from properly prepared cloud base template
  clone_vm_id             = "9002"
  
  # Modern EFI configuration with proper boot support
  bios                    = "ovmf"
  machine                 = "q35"  
  qemu_agent              = true
  
  efi_config {
    efi_storage_pool      = "rbd"
    pre_enrolled_keys     = false
    efi_type             = "4m"
  }
  
  # Network with VirtIO on management bridge (vmbr0) but boot from disk only
  network_adapters {
    bridge   = "vmbr0"
    model    = "virtio"
    firewall = false
  }
  
  # Force boot from disk only - completely disable network boot
  boot = "order=scsi0"
  
  # SSH configuration - using sysadmin user from prepared image
  ssh_username            = "sysadmin"
  ssh_password            = "password"
  ssh_private_key_file    = "/home/sysadmin/.ssh/sysadmin_automation_key"
  ssh_timeout             = "60m"
  ssh_port                = 22
  ssh_handshake_attempts  = 50
  ssh_wait_timeout        = "20m"
  
  # Timeout configurations
  task_timeout            = "10m"
}

build {
  sources = ["source.proxmox-clone.ubuntu-cloud"]
  
  # Wait for cloud-init and apt locks to clear
  provisioner "shell" {
    inline = [
      "echo 'Waiting for cloud-init to complete...'",
      "cloud-init status --wait || true",
      "echo 'Waiting for apt locks to clear...'",
      "while fuser /var/lib/apt/lists/lock >/dev/null 2>&1; do echo 'Waiting for apt-get process to finish...'; sleep 10; done",
      "while fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1; do echo 'Waiting for dpkg process to finish...'; sleep 10; done",
      "while fuser /var/lib/dpkg/lock >/dev/null 2>&1; do echo 'Waiting for dpkg lock to clear...'; sleep 10; done",
      "echo 'All locks cleared, proceeding...'"
    ]
  }
  
  # Update system and ensure qemu-guest-agent is running
  provisioner "shell" {
    inline = [
      "sudo apt-get update",
      "sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y",
      "sudo systemctl enable qemu-guest-agent",
      "sudo systemctl start qemu-guest-agent",
      "sudo systemctl status qemu-guest-agent --no-pager"
    ]
  }
  
  # Basic system optimization
  provisioner "shell" {
    inline = [
      "# Remove unnecessary packages",
      "sudo apt-get autoremove -y",
      "sudo apt-get autoclean",
      
      "# Clear logs and temporary files", 
      "sudo truncate -s 0 /var/log/*log || true",
      "sudo rm -rf /tmp/* /var/tmp/* || true",
      
      "# Clear bash history",
      "history -c || true",
      "cat /dev/null > ~/.bash_history || true"
    ]
  }
  
  # Final cleanup for template
  provisioner "shell" {
    inline = [
      "# Reset machine-id for template",
      "sudo truncate -s 0 /etc/machine-id",
      "sudo rm -f /var/lib/dbus/machine-id",
      
      "# Clean cloud-init for template use", 
      "sudo cloud-init clean --logs --seed || true",
      
      "# Final sync",
      "sync"
    ]
  }
}