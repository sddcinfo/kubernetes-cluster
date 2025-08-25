packer {
  required_plugins {
    proxmox = {
      version = ">= 1.1.3"
      source  = "github.com/hashicorp/proxmox"
    }
  }
}

source "proxmox-clone" "ubuntu-minimal" {
  proxmox_url              = "https://10.10.1.21:8006/api2/json"
  token                    = "7b2a3da7-bd30-4772-a6b0-874aa9b2f3a5"
  username                 = "packer@pam!packer"
  insecure_skip_tls_verify = true
  
  node         = "node1"
  vm_id        = "9000"
  vm_name      = "packer-test-minimal"
  template_description = "Test minimal Ubuntu template with qemu-guest-agent"
  
  # Clone from our minimal base template
  clone_vm_id = "9001"
  
  # Basic configuration
  cores   = "2"
  memory  = "2048"
  
  ssh_username         = "ubuntu"
  ssh_private_key_file = "~/.ssh/sysadmin_automation_key"
  ssh_timeout          = "20m"   # Extended timeout based on working examples
  ssh_handshake_attempts = 50    # Reasonable retry attempts
  ssh_pty              = true    # Enable pseudo-terminal
  task_timeout         = "10m"   # Task execution timeout
  
  # Enable QEMU guest agent for IP address detection
  qemu_agent = true
}

build {
  sources = ["source.proxmox-clone.ubuntu-minimal"]
  
  provisioner "shell" {
    inline = [
      "echo 'Testing minimal template - SSH connection successful!'",
      "echo 'qemu-guest-agent status:'",
      "systemctl is-active qemu-guest-agent",
      "echo 'Template test complete!'"
    ]
  }
}