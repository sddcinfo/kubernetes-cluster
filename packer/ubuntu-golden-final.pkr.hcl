packer {
  required_plugins {
    proxmox = {
      version = ">= 1.1.3"
      source  = "github.com/hashicorp/proxmox"
    }
  }
}

# Variables for flexibility across environments
variable "proxmox_url" {
  type        = string
  description = "Proxmox API URL"
  default     = "https://10.10.1.21:8006/api2/json"
}

variable "proxmox_token" {
  type        = string
  description = "Proxmox API token (format: user@realm!tokenname=secret)"
  default     = "packer@pam!packer=7b2a3da7-bd30-4772-a6b0-874aa9b2f3a5"
}

variable "proxmox_username" {
  type        = string
  description = "Proxmox username"
  default     = "packer@pam!packer"
}

variable "ssh_private_key" {
  type        = string
  description = "Path to SSH private key"
  default     = "~/.ssh/sysadmin_automation_key"
}

variable "base_template_id" {
  type        = number
  description = "Base template VM ID to clone from"
  default     = 9001
}

variable "golden_template_id" {
  type        = number
  description = "Golden template VM ID to create"
  default     = 9003
}

source "proxmox-clone" "ubuntu-golden" {
  proxmox_url              = var.proxmox_url
  token                    = var.proxmox_token
  username                 = var.proxmox_username
  insecure_skip_tls_verify = true
  
  node         = "node1"
  vm_id        = var.golden_template_id
  vm_name      = "ubuntu-2404-golden-template"
  template_description = "Ubuntu 24.04.3 LTS Golden Image - Production Ready with All Fixes Applied"
  
  # Clone from our minimal base template
  clone_vm_id = var.base_template_id
  
  # Production configuration
  cores   = "2"
  memory  = "2048"
  
  # CRITICAL SETTINGS - These are the PROVEN working configurations from our trial and error:
  ssh_username         = "ubuntu"
  ssh_private_key_file = var.ssh_private_key
  ssh_timeout          = "20m"   # CRITICAL: Extended timeout - was causing failures at 5m
  ssh_handshake_attempts = 50    # Reasonable retry attempts
  ssh_pty              = true    # Enable pseudo-terminal - required for some operations
  task_timeout         = "10m"   # Task execution timeout
  
  # CRITICAL: Enable QEMU guest agent for IP address detection
  # This was the root cause of many SSH timeout issues
  qemu_agent = true
}

build {
  sources = ["source.proxmox-clone.ubuntu-golden"]
  
  # Wait for system to be ready (learned from failures)
  provisioner "shell" {
    inline = [
      "echo 'Waiting for system to be ready...'",
      "sleep 30",
      "echo 'System ready, proceeding with golden image creation'"
    ]
  }
  
  # System updates and essential tools
  provisioner "shell" {
    inline = [
      "echo '=== Creating Ubuntu 24.04.3 Golden Image ==='",
      "echo 'Starting system updates...'",
      "sudo apt-get update",
      "sudo apt-get upgrade -y",
      
      "echo '=== Installing essential system tools ==='", 
      "sudo apt-get install -y curl wget gpg software-properties-common apt-transport-https ca-certificates",
      "sudo apt-get install -y htop iotop netstat-nat tcpdump tree vim nano",
      "sudo apt-get install -y net-tools dnsutils iputils-ping",
      
      "echo '=== Ensuring QEMU guest agent is properly configured ==='",
      "sudo apt-get install -y qemu-guest-agent",
      "sudo systemctl enable qemu-guest-agent",
      "sudo systemctl start qemu-guest-agent",
      "sudo systemctl is-active qemu-guest-agent",  # Verify it's running
      
      "echo '=== Installing NTP for time synchronization ==='", 
      "sudo apt-get install -y chrony",
      "sudo systemctl enable chrony",
      
      "echo '=== Basic security hardening ==='",
      "sudo apt-get install -y fail2ban ufw",
      "sudo systemctl enable fail2ban",
      
      "echo '=== System optimizations ==='",
      "echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf",
      "echo 'net.core.rmem_max=134217728' | sudo tee -a /etc/sysctl.conf", 
      "echo 'net.core.wmem_max=134217728' | sudo tee -a /etc/sysctl.conf",
      
      "echo '=== Installing cloud-init and ensuring proper configuration ==='",
      "sudo apt-get install -y cloud-init",
      "sudo systemctl enable cloud-init",
      
      "echo '=== Cleanup and optimization ==='",
      "sudo apt-get autoremove -y",
      "sudo apt-get autoclean",
      "sudo rm -rf /var/lib/apt/lists/*",
      
      # Clean logs but don't fail if files don't exist
      "sudo truncate -s 0 /var/log/*log 2>/dev/null || true",
      
      # Clean history files safely
      "history -c 2>/dev/null || true",
      "cat /dev/null > ~/.bash_history 2>/dev/null || true"
    ]
  }
  
  # Final verification and golden image validation
  provisioner "shell" {
    inline = [
      "echo '=== Golden Image Build Verification ==='",
      "echo 'Ubuntu Version:'", 
      "lsb_release -a",
      "echo ''",
      "echo 'Kernel Version:'",
      "uname -r",
      "echo ''",
      "echo 'QEMU Guest Agent Status:'",
      "systemctl is-active qemu-guest-agent",
      "systemctl status qemu-guest-agent --no-pager",
      "echo ''",
      "echo 'Cloud-init Status:'",
      "systemctl is-active cloud-init",
      "echo ''",
      "echo 'Disk Usage:'",
      "df -h /",
      "echo ''",
      "echo 'Memory:'",
      "free -h",
      "echo ''",
      "echo 'Network Configuration:'",
      "ip addr show",
      "echo ''",
      "echo 'Essential Services Status:'",
      "systemctl is-active ssh",
      "systemctl is-active chrony",
      "systemctl is-active fail2ban",
      "echo ''",
      "echo '=== Golden Image Ready for Production Deployment! ==='",
      "echo 'Template ID: ${var.golden_template_id}'",
      "echo 'Template Name: ubuntu-2404-golden-template'",
      "echo 'Build completed: $(date)'",
      "echo 'All learned fixes have been applied successfully!'"
    ]
  }
}