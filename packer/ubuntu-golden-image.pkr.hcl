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
  vm_id        = "9002"
  vm_name      = "ubuntu-2404-golden-template"
  template_description = "Ubuntu 24.04.3 LTS Golden Image - Production Ready"
  
  # Clone from our minimal base template
  clone_vm_id = "9001"
  
  # Production configuration
  cores   = "2"
  memory  = "2048"
  
  # Proven SSH configuration that works
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
  sources = ["source.proxmox-clone.ubuntu-golden"]
  
  # Wait for cloud-init to complete
  provisioner "shell" {
    inline = [
      "echo 'Waiting for cloud-init to complete...'",
      "sudo cloud-init status --wait",
      "echo 'Cloud-init completed successfully'"
    ]
  }
  
  # System updates and hardening
  provisioner "shell" {
    inline = [
      "echo '=== Updating Ubuntu 24.04.3 to latest patches ==='",
      "sudo apt-get update",
      "sudo DEBIAN_FRONTEND=noninteractive apt-get full-upgrade -y",
      "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y curl wget gpg software-properties-common apt-transport-https ca-certificates",
      
      "echo '=== Installing essential tools ==='", 
      "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y htop iotop netstat-nat tcpdump tree vim nano",
      "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y net-tools dnsutils iputils-ping",
      
      "echo '=== Ensuring qemu-guest-agent is properly configured ==='",
      "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y qemu-guest-agent",
      "sudo systemctl enable qemu-guest-agent",
      "sudo systemctl start qemu-guest-agent",
      
      "echo '=== Installing NTP for time synchronization ==='", 
      "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y chrony",
      "sudo systemctl enable chrony",
      
      "echo '=== Security hardening ==='",
      "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y fail2ban ufw",
      "sudo systemctl enable fail2ban",
      
      "echo '=== System optimizations ==='",
      "echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf",
      "echo 'net.core.rmem_max=134217728' | sudo tee -a /etc/sysctl.conf", 
      "echo 'net.core.wmem_max=134217728' | sudo tee -a /etc/sysctl.conf",
      
      "echo '=== Cleanup ==='",
      "sudo apt-get autoremove -y",
      "sudo apt-get autoclean",
      "sudo rm -rf /var/lib/apt/lists/*",
      "sudo truncate -s 0 /var/log/*log 2>/dev/null || true",
      "history -c",
      "cat /dev/null > ~/.bash_history"
    ]
  }
  
  # Final verification
  provisioner "shell" {
    inline = [
      "echo '=== Golden Image Build Complete ==='",
      "echo 'Ubuntu Version:'", 
      "lsb_release -a",
      "echo 'Kernel Version:'",
      "uname -r",
      "echo 'QEMU Guest Agent:'",
      "systemctl is-active qemu-guest-agent",
      "echo 'Disk Usage:'",
      "df -h /",
      "echo 'Memory:'",
      "free -h",
      "echo 'Golden image ready for production use!'"
    ]
  }
}