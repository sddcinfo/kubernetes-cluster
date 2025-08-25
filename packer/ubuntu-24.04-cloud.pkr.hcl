packer {
  required_plugins {
    proxmox = {
      version = ">= 1.1.3"
      source  = "github.com/hashicorp/proxmox"
    }
  }
}

source "proxmox-clone" "ubuntu-k8s" {
  proxmox_url              = "https://10.10.1.21:8006/api2/json"
  token                    = "7b2a3da7-bd30-4772-a6b0-874aa9b2f3a5"
  username                 = "packer@pam!packer"
  insecure_skip_tls_verify = true
  
  node         = "node1"
  vm_id        = "9000"
  vm_name      = "packer-ubuntu-k8s-cloud"
  template_description = "Ubuntu 24.04 LTS with Kubernetes components - Cloud-init approach"
  
  # Clone from template - let me first create base template
  clone_vm_id = "9001"  # We'll create this first
  
  # High-performance configuration (optimized base template already has CPU/hardware settings)
  cores   = "4"
  memory  = "4096"
  
  ssh_username         = "ubuntu"
  ssh_private_key_file = "~/.ssh/sysadmin_automation_key"
  ssh_timeout         = "10m"
}

build {
  sources = ["source.proxmox-clone.ubuntu-k8s"]
  
  # System updates and basic packages
  provisioner "shell" {
    inline = [
      "sudo apt-get update",
      "sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y",
      "sudo apt-get install -y apt-transport-https ca-certificates curl gpg software-properties-common"
    ]
  }
  
  # Install containerd
  provisioner "shell" {
    inline = [
      "curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg",
      "echo 'deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable' | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null",
      "sudo apt-get update",
      "sudo apt-get install -y containerd.io",
      "sudo mkdir -p /etc/containerd",
      "containerd config default | sudo tee /etc/containerd/config.toml",
      "sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml",
      "sudo systemctl enable containerd"
    ]
  }
  
  # Install Kubernetes components
  provisioner "shell" {
    inline = [
      "curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.29/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg",
      "echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.29/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list",
      "sudo apt-get update",
      "sudo apt-get install -y kubelet=1.29.* kubeadm=1.29.* kubectl=1.29.*",
      "sudo apt-mark hold kubelet kubeadm kubectl"
    ]
  }
  
  # System configuration for Kubernetes
  provisioner "shell" {
    inline = [
      "sudo swapoff -a",
      "sudo sed -i '/ swap / s/^/#/' /etc/fstab",
      "echo 'net.ipv4.ip_forward=1' | sudo tee -a /etc/sysctl.conf",
      "echo 'net.bridge.bridge-nf-call-ip6tables=1' | sudo tee -a /etc/sysctl.conf",
      "echo 'net.bridge.bridge-nf-call-iptables=1' | sudo tee -a /etc/sysctl.conf",
      "sudo modprobe br_netfilter || true",
      "echo 'br_netfilter' | sudo tee /etc/modules-load.d/k8s.conf"
    ]
  }
  
  # Install keepalived for HA
  provisioner "shell" {
    inline = [
      "sudo apt-get install -y keepalived"
    ]
  }
  
  # Cleanup
  provisioner "shell" {
    inline = [
      "sudo apt-get autoremove -y",
      "sudo apt-get autoclean",
      "sudo rm -rf /var/lib/apt/lists/*",
      "sudo truncate -s 0 /var/log/*log || true",
      "history -c",
      "cat /dev/null > ~/.bash_history"
    ]
  }
}