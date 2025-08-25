packer {
  required_plugins {
    proxmox = {
      version = ">= 1.1.3"
      source  = "github.com/hashicorp/proxmox"
    }
  }
}

source "proxmox-clone" "ubuntu-golden" {
  proxmox_url              = "https://10.10.1.21:8006/api2/json"
  token                    = "7b2a3da7-bd30-4772-a6b0-874aa9b2f3a5"
  username                 = "packer@pam!packer"
  insecure_skip_tls_verify = true
  
  node         = "node1"
  vm_id        = "9003"
  vm_name      = "ubuntu-2404-golden-template"
  template_description = "Ubuntu 24.04.3 LTS Golden Image - Updated with QEMU Agent"
  
  # Clone from our minimal base template
  clone_vm_id = "9001"
  
  # Basic configuration
  cores   = "2"
  memory  = "2048"
  
  # SSH configuration
  ssh_username         = "ubuntu"
  ssh_private_key_file = "~/.ssh/sysadmin_automation_key"
  ssh_timeout          = "20m"
  ssh_handshake_attempts = 50
  ssh_pty              = true
  task_timeout         = "10m"
  
  # Enable QEMU guest agent for IP address detection
  qemu_agent = true
}

build {
  sources = ["source.proxmox-clone.ubuntu-golden"]
  
  # Wait for system to be ready
  provisioner "shell" {
    inline = [
      "echo 'Waiting for system to be ready...'",
      "sleep 30"
    ]
  }
  
  # Update system and ensure QEMU guest agent is running
  provisioner "shell" {
    inline = [
      "echo 'Updating system packages...'",
      "sudo apt-get update",
      "sudo apt-get upgrade -y",
      
      "echo 'Ensuring QEMU guest agent is running...'",
      "sudo systemctl start qemu-guest-agent",
      "sudo systemctl is-active qemu-guest-agent",
      
      "echo 'Cleaning up...'",
      "sudo apt-get autoremove -y",
      "sudo apt-get autoclean"
    ]
  }
  
  # Verification
  provisioner "shell" {
    inline = [
      "echo 'Golden Image Build Complete'",
      "echo 'Ubuntu Version:'", 
      "lsb_release -a",
      "echo 'QEMU Guest Agent Status:'",
      "systemctl is-active qemu-guest-agent"
    ]
  }
}