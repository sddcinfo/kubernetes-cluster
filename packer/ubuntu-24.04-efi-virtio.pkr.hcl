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
  vm_name      = "packer-ubuntu-k8s-efi-virtio"
  template_description = "Ubuntu 24.04 LTS with Kubernetes 1.33 - Modern EFI+VirtIO"
  
  # Clone from our modern EFI+VirtIO base template
  clone_vm_id = "9001"
  
  # Performance configuration (hardware inherited from base template)
  # Base template includes: host CPU, NUMA, VirtIO, multi-queue networking,
  # writeback cache, discard, iothread, and entropy device
  cores   = "4"     # Increase cores for Kubernetes workloads
  memory  = "4096"  # 4GB RAM minimum for K8s
  
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
  sources = ["source.proxmox-clone.ubuntu-k8s"]
  
  provisioner "shell" {
    inline = [
      "while [ ! -f /var/lib/cloud/instance/boot-finished ]; do echo 'Waiting for cloud-init...'; sleep 1; done",
      "sleep 30"  # Give cloud-init extra time
    ]
  }
  
  provisioner "shell" {
    inline = [
      "sudo apt-get update",
      "sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y",
      "sudo apt-get install -y apt-transport-https ca-certificates curl gpg software-properties-common",
      "sudo apt-get install -y qemu-guest-agent"
    ]
  }
  
  provisioner "shell" {
    inline = [
      "curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg",
      "echo \"deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable\" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null",
      "sudo apt-get update",
      "sudo apt-get install -y containerd.io",
      "sudo mkdir -p /etc/containerd",
      "containerd config default | sudo tee /etc/containerd/config.toml",
      "sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml",
      "sudo systemctl enable containerd"
    ]
  }
  
  provisioner "shell" {
    inline = [
      "curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.33/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg",
      "echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.33/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list",
      "sudo apt-get update",
      "sudo apt-get install -y kubelet=1.33.* kubeadm=1.33.* kubectl=1.33.*",
      "sudo apt-mark hold kubelet kubeadm kubectl",
      "",
      "# Configure kubelet for modern container runtime",
      "sudo mkdir -p /etc/systemd/system/kubelet.service.d",
      "echo '[Service]' | sudo tee /etc/systemd/system/kubelet.service.d/20-etcd-service-manager.conf",
      "echo 'ExecStart=' | sudo tee -a /etc/systemd/system/kubelet.service.d/20-etcd-service-manager.conf",
      "echo 'ExecStart=/usr/bin/kubelet --config=/var/lib/kubelet/config.yaml --container-runtime-endpoint=unix:///var/run/containerd/containerd.sock --node-labels=node.kubernetes.io/instance-type=vm' | sudo tee -a /etc/systemd/system/kubelet.service.d/20-etcd-service-manager.conf"
    ]
  }
  
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
  
  # Install HA and monitoring tools
  provisioner "shell" {
    inline = [
      "sudo apt-get install -y keepalived haproxy",
      "",
      "# Install modern monitoring tools",
      "sudo apt-get install -y htop iotop netstat-nat tcpdump",
      "sudo apt-get install -y prometheus-node-exporter",
      "sudo systemctl enable prometheus-node-exporter",
      "",
      "# Install Helm for Kubernetes package management",
      "curl -fsSL https://baltocdn.com/helm/signing.asc | sudo gpg --dearmor -o /usr/share/keyrings/helm.gpg",
      "echo 'deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/helm.gpg] https://baltocdn.com/helm/stable/debian/ all main' | sudo tee /etc/apt/sources.list.d/helm-stable-debian.list",
      "sudo apt-get update",
      "sudo apt-get install -y helm",
      "",
      "# Install crictl for container runtime debugging",
      "CRICTL_VERSION=v1.33.1",
      "wget -q https://github.com/kubernetes-sigs/cri-tools/releases/download/$CRICTL_VERSION/crictl-$CRICTL_VERSION-linux-amd64.tar.gz",
      "sudo tar zxvf crictl-$CRICTL_VERSION-linux-amd64.tar.gz -C /usr/local/bin",
      "rm -f crictl-$CRICTL_VERSION-linux-amd64.tar.gz",
      "echo 'runtime-endpoint: unix:///run/containerd/containerd.sock' | sudo tee /etc/crictl.yaml"
    ]
  }
  
  # Modern system optimizations for Kubernetes + Ceph
  provisioner "shell" {
    inline = [
      "# Enable fstrim service for SSD/RBD optimization",
      "sudo systemctl enable fstrim.timer",
      "",
      "# Optimize systemd for containers",
      "echo 'DefaultTasksMax=infinity' | sudo tee -a /etc/systemd/system.conf",
      "echo 'DefaultLimitNOFILE=1048576' | sudo tee -a /etc/systemd/system.conf",
      "",
      "# Kernel optimizations for Kubernetes",
      "echo 'vm.max_map_count=262144' | sudo tee -a /etc/sysctl.conf",
      "echo 'fs.inotify.max_user_instances=8192' | sudo tee -a /etc/sysctl.conf",
      "echo 'fs.inotify.max_user_watches=1048576' | sudo tee -a /etc/sysctl.conf",
      "",
      "# Network performance tuning",
      "echo 'net.core.rmem_max=134217728' | sudo tee -a /etc/sysctl.conf",
      "echo 'net.core.wmem_max=134217728' | sudo tee -a /etc/sysctl.conf",
      "echo 'net.ipv4.tcp_rmem=4096 87380 134217728' | sudo tee -a /etc/sysctl.conf",
      "echo 'net.ipv4.tcp_wmem=4096 65536 134217728' | sudo tee -a /etc/sysctl.conf",
      "",
      "# Enable BBR congestion control for better network performance",
      "echo 'net.core.default_qdisc=fq' | sudo tee -a /etc/sysctl.conf",
      "echo 'net.ipv4.tcp_congestion_control=bbr' | sudo tee -a /etc/sysctl.conf",
      "",
      "# I/O scheduler optimization for Ceph RBD",
      "echo 'echo mq-deadline > /sys/block/*/queue/scheduler' | sudo tee /etc/rc.local",
      "sudo chmod +x /etc/rc.local",
      "",
      "# Install qemu-guest-agent for better VM integration",
      "sudo apt-get install -y qemu-guest-agent",
      "sudo systemctl enable qemu-guest-agent"
    ]
  }
  
  provisioner "shell" {
    inline = [
      "sudo apt-get autoremove -y",
      "sudo apt-get autoclean",
      "sudo rm -rf /var/lib/apt/lists/*",
      "sudo truncate -s 0 /var/log/*log",
      "history -c",
      "cat /dev/null > ~/.bash_history"
    ]
  }
}
