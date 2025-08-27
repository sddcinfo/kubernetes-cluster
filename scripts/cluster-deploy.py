#!/usr/bin/env python3
"""
Kubernetes Cluster Deployment Tool
Unified, modular deployment system for Kubernetes clusters on Proxmox
"""

import os
import sys
import json
import yaml
import time
import logging
import argparse
import subprocess
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/tmp/cluster-deploy.log')
    ]
)

class DeploymentProfile(Enum):
    """Predefined deployment profiles"""
    SINGLE_NODE = "single-node"
    SINGLE_MASTER = "single-master" 
    HA_CLUSTER = "ha-cluster"
    DEVELOPMENT = "development"
    PRODUCTION = "production"

class Component(Enum):
    """Deployable cluster components"""
    FOUNDATION = "foundation"
    PACKER_IMAGE = "packer-image"
    INFRASTRUCTURE = "infrastructure"
    KUBERNETES = "kubernetes"
    NETWORKING = "networking"
    STORAGE = "storage"
    MONITORING = "monitoring"
    INGRESS = "ingress"
    BACKUP = "backup"
    DASHBOARD = "dashboard"
    CERTIFICATES = "certificates"

class ClusterState:
    """Manages deployment state across components"""
    
    STATE_DIR = Path.home() / ".kube-cluster"
    STATE_FILE = STATE_DIR / "cluster-state.json"
    
    def __init__(self):
        self.STATE_DIR.mkdir(exist_ok=True)
        self.state = self.load_state()
    
    def load_state(self) -> Dict:
        if self.STATE_FILE.exists():
            with open(self.STATE_FILE, 'r') as f:
                return json.load(f)
        return {
            "deployment_profile": None,
            "components": {},
            "cluster_config": {},
            "last_updated": None,
            "version": "2.0"
        }
    
    def save_state(self):
        self.state["last_updated"] = datetime.now().isoformat()
        with open(self.STATE_FILE, 'w') as f:
            json.dump(self.state, f, indent=2)
    
    def set_component_state(self, component: Component, status: str, metadata: Dict = None):
        self.state["components"][component.value] = {
            "status": status,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {}
        }
        self.save_state()
    
    def get_component_state(self, component: Component) -> Optional[Dict]:
        return self.state["components"].get(component.value)
    
    def is_component_deployed(self, component: Component) -> bool:
        comp_state = self.get_component_state(component)
        return comp_state and comp_state.get("status") == "deployed"

class ComponentDeployer:
    """Base class for component deployment"""
    
    def __init__(self, config: Dict, state: ClusterState):
        self.config = config
        self.state = state
        self.logger = logging.getLogger(f"{self.__class__.__name__}")
    
    def run_command(self, cmd: str, timeout: int = 300, check: bool = True) -> subprocess.CompletedProcess:
        """Execute shell command with timeout"""
        self.logger.info(f"Running: {cmd}")
        try:
            result = subprocess.run(
                cmd, shell=True, check=check, 
                capture_output=True, text=True, timeout=timeout
            )
            if result.stdout:
                self.logger.debug(f"Output: {result.stdout}")
            return result
        except subprocess.TimeoutExpired:
            self.logger.error(f"Command timed out after {timeout}s: {cmd}")
            raise
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Command failed: {e}")
            if e.stdout:
                self.logger.error(f"stdout: {e.stdout}")
            if e.stderr:
                self.logger.error(f"stderr: {e.stderr}")
            raise
    
    def validate(self) -> bool:
        """Validate component prerequisites"""
        raise NotImplementedError
    
    def deploy(self) -> bool:
        """Deploy the component"""
        raise NotImplementedError
    
    def verify(self) -> bool:
        """Verify component deployment"""
        raise NotImplementedError
    
    def cleanup(self) -> bool:
        """Clean up component resources"""
        raise NotImplementedError

class FoundationDeployer(ComponentDeployer):
    """Foundation setup: DNS, SSH, basic configuration"""
    
    def validate(self) -> bool:
        # Check if foundation setup script exists (ping won't work due to firewall)
        foundation_script = Path("scripts/cluster-foundation-setup.py")
        if not foundation_script.exists():
            self.logger.error("Foundation setup script not found")
            return False
        return True
    
    def deploy(self) -> bool:
        self.logger.info("Deploying foundation components...")
        
        # Run foundation setup (existing script)
        result = self.run_command("python3 scripts/cluster-foundation-setup.py", timeout=600)
        
        self.state.set_component_state(
            Component.FOUNDATION, 
            "deployed",
            {"proxmox_host": self.config["proxmox"]["host"]}
        )
        return True
    
    def verify(self) -> bool:
        # Verify DNS resolution and SSH access
        try:
            self.run_command("nslookup packer.k8s.local", timeout=5)
            return True
        except:
            return False

class PackerImageDeployer(ComponentDeployer):
    """Kubernetes-ready VM image with pre-installed software"""
    
    def validate(self) -> bool:
        # Check if packer is available
        try:
            self.run_command("packer version", timeout=5)
            return True
        except:
            self.logger.error("Packer not found")
            return False
    
    def deploy(self) -> bool:
        self.logger.info("Building Kubernetes-ready image...")
        
        # Generate enhanced Packer configuration
        packer_config = self._generate_k8s_ready_config()
        
        with open("../packer/kubernetes-ready.pkr.hcl", "w") as f:
            f.write(packer_config)
        
        # Build image
        os.chdir("../packer")
        self.run_command("packer build kubernetes-ready.pkr.hcl", timeout=1800)
        os.chdir("../scripts")
        
        self.state.set_component_state(
            Component.PACKER_IMAGE,
            "deployed", 
            {
                "template_id": self.config.get("template_id", 9001),
                "k8s_version": self.config.get("kubernetes_version", "1.30.0")
            }
        )
        return True
    
    def _generate_k8s_ready_config(self) -> str:
        """Generate Packer config with Kubernetes pre-installed"""
        return f'''
packer {{
  required_plugins {{
    proxmox = {{
      version = ">= 1.1.8"
      source  = "github.com/hashicorp/proxmox"
    }}
  }}
}}

variable "proxmox_host" {{
  type    = string
  default = "{self.config["proxmox"]["host"]}:8006"
}}

variable "proxmox_token" {{
  type    = string  
  default = "{self.config["proxmox"]["token"]}"
}}

variable "template_name" {{
  type    = string
  default = "kubernetes-ready-template"
}}

variable "template_id" {{
  type    = string
  default = "{self.config.get('template_id', 9001)}"
}}

source "proxmox-clone" "kubernetes-ready" {{
  proxmox_url              = "https://${{var.proxmox_host}}/api2/json"
  username                = "packer@pam!packer"
  token                   = var.proxmox_token
  insecure_skip_tls_verify = true
  
  vm_name                 = var.template_name
  vm_id                   = var.template_id
  template_name           = var.template_name
  template_description    = "Kubernetes-ready Ubuntu 24.04 template with pre-installed K8s components"
  
  node                    = "node1"
  cores                   = 2
  memory                  = 4096
  
  # Hardware configuration to match base template
  cpu_type                = "host"
  os                      = "l26"
  scsi_controller         = "virtio-scsi-pci"
  
  # Clone from cloud-base template (reliable network config)
  clone_vm                = "ubuntu-cloud-base"
  
  # Modern EFI configuration with proper boot support
  bios                    = "ovmf"
  machine                 = "q35"  
  qemu_agent              = true
  
  efi_config {{
    efi_storage_pool      = "rbd"
    pre_enrolled_keys     = false
    efi_type             = "4m"
  }}
  
  # Network with VirtIO on management bridge
  network_adapters {{
    bridge   = "vmbr0"
    model    = "virtio"
    firewall = false
  }}
  
  # Force boot from disk only
  boot = "order=scsi0"
  
  # SSH configuration - using sysadmin user from prepared image  
  ssh_username            = "sysadmin"
  ssh_private_key_file    = "/home/sysadmin/.ssh/sysadmin_automation_key"
  ssh_timeout             = "60m"
  ssh_port                = 22
  ssh_handshake_attempts  = 50
  ssh_wait_timeout        = "20m"
  
  # Timeout configurations
  task_timeout            = "10m"
}}

build {{
  sources = ["source.proxmox-clone.kubernetes-ready"]
  
  # Update system
  provisioner "shell" {{
    inline = [
      "sudo apt-get update",
      "sudo apt-get upgrade -y"
    ]
  }}
  
  # Install Kubernetes components
  provisioner "shell" {{
    inline = [
      "curl -fsSL https://pkgs.k8s.io/core:/stable:/v{self.config.get('kubernetes_version', '1.30')}/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg",
      "echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v{self.config.get('kubernetes_version', '1.30')}/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list",
      "sudo apt-get update",
      "sudo apt-get install -y kubelet={self.config.get('kubernetes_version', '1.30.0')}-1.1 kubeadm={self.config.get('kubernetes_version', '1.30.0')}-1.1 kubectl={self.config.get('kubernetes_version', '1.30.0')}-1.1",
      "sudo apt-mark hold kubelet kubeadm kubectl"
    ]
  }}
  
  # Install containerd
  provisioner "shell" {{
    inline = [
      "sudo apt-get install -y containerd",
      "sudo mkdir -p /etc/containerd",
      "containerd config default | sudo tee /etc/containerd/config.toml",
      "sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml",
      "sudo systemctl restart containerd",
      "sudo systemctl enable containerd"
    ]
  }}
  
  # Install additional tools
  provisioner "shell" {{
    inline = [
      "sudo apt-get install -y curl wget gpg lsb-release ca-certificates",
      "curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg",
      "sudo apt-get install -y htop iotop nethogs iftop vim"
    ]
  }}
  
  # Configure kernel modules and sysctl
  provisioner "shell" {{
    inline = [
      "echo 'br_netfilter' | sudo tee /etc/modules-load.d/k8s.conf",
      "echo 'overlay' | sudo tee -a /etc/modules-load.d/k8s.conf",
      "sudo modprobe br_netfilter",
      "sudo modprobe overlay",
      "echo 'net.bridge.bridge-nf-call-iptables = 1' | sudo tee /etc/sysctl.d/k8s.conf",
      "echo 'net.bridge.bridge-nf-call-ip6tables = 1' | sudo tee -a /etc/sysctl.d/k8s.conf", 
      "echo 'net.ipv4.ip_forward = 1' | sudo tee -a /etc/sysctl.d/k8s.conf",
      "sudo sysctl --system"
    ]
  }}
  
  # Disable swap
  provisioner "shell" {{
    inline = [
      "sudo swapoff -a",
      "sudo sed -i '/ swap / s/^/#/' /etc/fstab"
    ]
  }}
  
  # Clean up
  provisioner "shell" {{
    inline = [
      "sudo apt-get autoremove -y",
      "sudo apt-get autoclean",
      "sudo rm -rf /var/cache/apt/archives/*",
      "history -c"
    ]
  }}
}}
'''

class InfrastructureDeployer(ComponentDeployer):
    """VM infrastructure deployment"""
    
    def validate(self) -> bool:
        # Check if terraform/tofu is available
        for cmd in ["tofu", "terraform"]:
            try:
                self.run_command(f"{cmd} version", timeout=5)
                self.tf_cmd = cmd
                return True
            except:
                continue
        self.logger.error("Neither OpenTofu nor Terraform found")
        return False
    
    def deploy(self) -> bool:
        self.logger.info("Deploying infrastructure...")
        
        profile = self.config.get("deployment_profile", "ha-cluster")
        
        # Generate Terraform configuration based on profile
        tf_config = self._generate_terraform_config(profile)
        
        with open("../terraform/main.tf", "w") as f:
            f.write(tf_config)
        
        # Deploy infrastructure
        os.chdir("../terraform")
        self.run_command(f"{self.tf_cmd} init", timeout=300)
        self.run_command(f"{self.tf_cmd} plan -out=tfplan", timeout=300)
        self.run_command(f"{self.tf_cmd} apply tfplan", timeout=600)
        
        # Generate inventory
        inventory = self.run_command(f"{self.tf_cmd} output -raw ansible_inventory").stdout
        with open("../ansible/inventory.yml", "w") as f:
            f.write(inventory)
        
        os.chdir("../scripts")
        
        self.state.set_component_state(
            Component.INFRASTRUCTURE,
            "deployed",
            {"profile": profile, "terraform_cmd": self.tf_cmd}
        )
        return True
    
    def _generate_terraform_config(self, profile: str) -> str:
        """Generate Terraform config based on deployment profile"""
        
        if profile == "single-node":
            control_nodes, worker_nodes = 1, 0
        elif profile == "single-master":
            control_nodes, worker_nodes = 1, 2
        else:  # ha-cluster or production
            control_nodes, worker_nodes = 3, 4
        
        return f'''
terraform {{
  required_providers {{
    proxmox = {{
      source  = "bpg/proxmox"
      version = "~> 0.70"
    }}
  }}
}}

provider "proxmox" {{
  endpoint = "https://{self.config['proxmox']['host']}:8006/"
  api_token = "{self.config['proxmox']['token']}"
  insecure = true
  ssh {{ agent = true }}
}}

# Control Plane Nodes
resource "proxmox_virtual_environment_vm" "control_plane" {{
  count = {control_nodes}
  
  name      = "k8s-control-${{count.index + 1}}"
  node_name = "hp4"
  vm_id     = 200 + count.index
  
  clone {{
    vm_id = {self.config.get('template_id', 9001)}
    full  = true
  }}
  
  cpu {{ cores = 4; type = "host" }}
  memory {{ dedicated = 8192 }}
  
  disk {{
    datastore_id = "rbd"
    size         = 50
    interface    = "scsi0"
  }}
  
  network_device {{
    bridge = "vmbr1"
    model  = "virtio"
  }}
  
  initialization {{
    ip_config {{
      ipv4 {{
        address = "10.10.1.${{100 + count.index}}/24"
        gateway = "10.10.1.1"
      }}
    }}
    user_data_file_id = proxmox_virtual_environment_file.cloud_config.id
  }}
  
  started = true
}}

# Worker Nodes (only if worker_nodes > 0)
{"" if worker_nodes == 0 else f'''
resource "proxmox_virtual_environment_vm" "worker" {{
  count = {worker_nodes}
  
  name      = "k8s-worker-${{count.index + 1}}"
  node_name = "hp4"
  vm_id     = 210 + count.index
  
  clone {{
    vm_id = {self.config.get('template_id', 9001)}
    full  = true
  }}
  
  cpu {{ cores = 4; type = "host" }}
  memory {{ dedicated = 16384 }}
  
  disk {{
    datastore_id = "rbd"
    size         = 100
    interface    = "scsi0"
  }}
  
  network_device {{
    bridge = "vmbr1"
    model  = "virtio"
  }}
  
  initialization {{
    ip_config {{
      ipv4 {{
        address = "10.10.1.${{110 + count.index}}/24"
        gateway = "10.10.1.1"
      }}
    }}
    user_data_file_id = proxmox_virtual_environment_file.cloud_config.id
  }}
  
  started = true
}}
'''}

resource "proxmox_virtual_environment_file" "cloud_config" {{
  content_type = "snippets"
  datastore_id = "local"
  node_name    = "hp4"
  
  source_raw {{
    data = <<-EOT
    #cloud-config
    users:
      - name: ubuntu
        sudo: ALL=(ALL) NOPASSWD:ALL
        groups: users, admin
        shell: /bin/bash
        ssh_authorized_keys:
          - ${{file("~/.ssh/id_rsa.pub")}}
    package_update: true
    package_upgrade: false
    runcmd:
      - systemctl restart systemd-networkd
      - systemctl restart systemd-resolved
    EOT
    file_name = "k8s-cloud-config.yaml"
  }}
}}

# Generate Ansible inventory
output "ansible_inventory" {{
  value = templatefile("${{path.module}}/templates/inventory.tpl", {{
    control_nodes = proxmox_virtual_environment_vm.control_plane
    worker_nodes  = {"[]" if worker_nodes == 0 else "proxmox_virtual_environment_vm.worker"}
    single_node   = {str(control_nodes == 1 and worker_nodes == 0).lower()}
  }})
}}
'''

class KubernetesDeployer(ComponentDeployer):
    """Kubernetes cluster bootstrap"""
    
    def validate(self) -> bool:
        # Check Ansible and kubectl
        try:
            self.run_command("ansible --version", timeout=5)
            return True
        except:
            self.logger.error("Ansible not found")
            return False
    
    def deploy(self) -> bool:
        self.logger.info("Bootstrapping Kubernetes cluster...")
        
        profile = self.config.get("deployment_profile", "ha-cluster")
        playbook = self._generate_k8s_playbook(profile)
        
        with open("../ansible/bootstrap-k8s.yml", "w") as f:
            f.write(playbook)
        
        # Run Ansible playbook
        self.run_command(
            "ansible-playbook -i ../ansible/inventory.yml ../ansible/bootstrap-k8s.yml",
            timeout=1800
        )
        
        # Copy kubeconfig
        self.run_command("mkdir -p ~/.kube")
        self.run_command(
            "scp ubuntu@10.10.1.100:/home/ubuntu/.kube/config ~/.kube/config-k8s-cluster",
            timeout=30
        )
        
        self.state.set_component_state(
            Component.KUBERNETES,
            "deployed",
            {"profile": profile, "kubeconfig": "~/.kube/config-k8s-cluster"}
        )
        return True
    
    def _generate_k8s_playbook(self, profile: str) -> str:
        """Generate Kubernetes bootstrap playbook"""
        
        single_node = profile == "single-node"
        
        return f'''---
- name: Bootstrap Kubernetes Cluster
  hosts: all
  become: yes
  tasks:
    - name: Ensure containerd is running
      systemd:
        name: containerd
        state: started
        enabled: yes
    
    - name: Ensure kubelet is enabled
      systemd:
        name: kubelet
        enabled: yes

- name: Initialize Kubernetes cluster
  hosts: control_plane[0]
  become: yes
  vars:
    kubeadm_config: |
      apiVersion: kubeadm.k8s.io/v1beta3
      kind: InitConfiguration
      localAPIEndpoint:
        advertiseAddress: "{{{{ ansible_default_ipv4.address }}}}"
        bindPort: 6443
      ---
      apiVersion: kubeadm.k8s.io/v1beta3  
      kind: ClusterConfiguration
      kubernetesVersion: v{self.config.get('kubernetes_version', '1.33.4')}
      {"# Single node - no control plane endpoint" if single_node else 'controlPlaneEndpoint: "10.10.1.99:6443"'}
      networking:
        podSubnet: 10.244.0.0/16
        serviceSubnet: 10.96.0.0/12
      {"---" if not single_node else ""}
      {"apiVersion: kubelet.config.k8s.io/v1beta1" if not single_node else ""}
      {"kind: KubeletConfiguration" if not single_node else ""}
      {"cgroupDriver: systemd" if not single_node else ""}
  
  tasks:
    - name: Check if cluster is already initialized
      stat:
        path: /etc/kubernetes/admin.conf
      register: kubeadm_init
    
    - name: Create kubeadm config file
      copy:
        content: "{{{{ kubeadm_config }}}}"
        dest: /tmp/kubeadm-config.yaml
      when: not kubeadm_init.stat.exists
    
    - name: Initialize Kubernetes cluster
      command: kubeadm init --config=/tmp/kubeadm-config.yaml {"" if single_node else "--upload-certs"}
      when: not kubeadm_init.stat.exists
    
    {"# Single node: remove master taint" if single_node else ""}
    {"- name: Remove master taint for single node" if single_node else ""}
    {"  command: kubectl taint nodes --all node-role.kubernetes.io/control-plane-" if single_node else ""}
    {"  become_user: ubuntu" if single_node else ""}
    {"  environment:" if single_node else ""}
    {"    KUBECONFIG: /home/ubuntu/.kube/config" if single_node else ""}
    {"  when: not kubeadm_init.stat.exists" if single_node else ""}
    
    - name: Create .kube directory
      file:
        path: /home/ubuntu/.kube
        state: directory
        owner: ubuntu
        group: ubuntu
        mode: '0755'
    
    - name: Copy admin.conf to ubuntu user
      copy:
        src: /etc/kubernetes/admin.conf
        dest: /home/ubuntu/.kube/config
        owner: ubuntu
        group: ubuntu
        mode: '0644'
        remote_src: yes

{"# Multi-node cluster setup" if not single_node else ""}
{"- name: Get join commands" if not single_node else ""}
{"  hosts: control_plane[0]" if not single_node else ""}
{"  become: yes" if not single_node else ""}
{"  tasks:" if not single_node else ""}
{"    - name: Get join command for workers" if not single_node else ""}
{"      command: kubeadm token create --print-join-command" if not single_node else ""}
{"      register: worker_join_command" if not single_node else ""}

{"- name: Join worker nodes" if not single_node else ""}
{"  hosts: workers" if not single_node else ""}
{"  become: yes" if not single_node else ""}
{"  tasks:" if not single_node else ""}
{"    - name: Join cluster as worker" if not single_node else ""}
{"      command: \"{{{{ hostvars[groups['control_plane'][0]]['worker_join_command']['stdout'] }}}}\"" if not single_node else ""}
{"      when: not (stat_result.stat.exists | default(false))" if not single_node else ""}

- name: Install CNI
  hosts: control_plane[0]
  become_user: ubuntu
  tasks:
    - name: Install Cilium CNI
      shell: |
        curl -L --remote-name-all https://github.com/cilium/cilium-cli/releases/latest/download/cilium-linux-amd64.tar.gz
        sudo tar xzvfC cilium-linux-amd64.tar.gz /usr/local/bin
        cilium install --version 1.15.0
      args:
        creates: /usr/local/bin/cilium
      environment:
        KUBECONFIG: /home/ubuntu/.kube/config
'''

class ClusterDeploymentOrchestrator:
    """Main orchestrator for modular cluster deployment"""
    
    def __init__(self, config_path: Optional[str] = None):
        self.state = ClusterState()
        self.config = self._load_config(config_path)
        self.deployers = self._initialize_deployers()
        self.logger = logging.getLogger("ClusterOrchestrator")
    
    def _load_config(self, config_path: Optional[str]) -> Dict:
        """Load deployment configuration"""
        default_config = {
            "deployment_profile": "ha-cluster",
            "kubernetes_version": "1.33.4", 
            "template_id": 9005,
            "proxmox": {
                "host": "10.10.1.21",
                "token": "packer@pam!packer=7b2a3da7-bd30-4772-a6b0-874aa9b2f3a5"
            }
        }
        
        if config_path and Path(config_path).exists():
            with open(config_path, 'r') as f:
                if config_path.endswith('.yaml') or config_path.endswith('.yml'):
                    user_config = yaml.safe_load(f)
                else:
                    user_config = json.load(f)
            default_config.update(user_config)
        
        return default_config
    
    def _initialize_deployers(self) -> Dict[Component, ComponentDeployer]:
        """Initialize component deployers"""
        return {
            Component.FOUNDATION: FoundationDeployer(self.config, self.state),
            Component.PACKER_IMAGE: PackerImageDeployer(self.config, self.state),
            Component.INFRASTRUCTURE: InfrastructureDeployer(self.config, self.state),
            Component.KUBERNETES: KubernetesDeployer(self.config, self.state)
        }
    
    def deploy_components(self, components: List[Component], force: bool = False) -> bool:
        """Deploy specified components"""
        self.logger.info(f"Deploying components: {[c.value for c in components]}")
        
        for component in components:
            if component not in self.deployers:
                self.logger.warning(f"No deployer for component: {component.value}")
                continue
            
            if not force and self.state.is_component_deployed(component):
                self.logger.info(f"Component {component.value} already deployed, skipping")
                continue
            
            deployer = self.deployers[component]
            
            self.logger.info(f"Validating {component.value}...")
            if not deployer.validate():
                self.logger.error(f"Validation failed for {component.value}")
                return False
            
            self.logger.info(f"Deploying {component.value}...")
            try:
                if not deployer.deploy():
                    self.logger.error(f"Deployment failed for {component.value}")
                    return False
                
                if not deployer.verify():
                    self.logger.error(f"Verification failed for {component.value}")
                    return False
                
                self.logger.info(f"Successfully deployed {component.value}")
                
            except Exception as e:
                self.logger.error(f"Error deploying {component.value}: {e}")
                return False
        
        return True
    
    def deploy_profile(self, profile: DeploymentProfile, force: bool = False) -> bool:
        """Deploy complete cluster based on profile"""
        self.config["deployment_profile"] = profile.value
        self.state.state["deployment_profile"] = profile.value
        self.state.save_state()
        
        if profile == DeploymentProfile.SINGLE_NODE:
            components = [
                Component.FOUNDATION,
                Component.PACKER_IMAGE, 
                Component.INFRASTRUCTURE,
                Component.KUBERNETES
            ]
        else:
            components = [
                Component.FOUNDATION,
                Component.PACKER_IMAGE,
                Component.INFRASTRUCTURE, 
                Component.KUBERNETES
            ]
        
        return self.deploy_components(components, force)
    
    def status(self):
        """Display deployment status"""
        print("\\nCluster Deployment Status")
        print("=" * 50)
        print(f"Profile: {self.state.state.get('deployment_profile', 'Not set')}")
        print(f"Last Updated: {self.state.state.get('last_updated', 'Never')}")
        print()
        
        for component in Component:
            state = self.state.get_component_state(component)
            if state:
                status = state['status']
                timestamp = state['timestamp']
                print(f"  {component.value:15}: {status:10} ({timestamp})")
            else:
                print(f"  {component.value:15}: {'not deployed':10}")

def main():
    parser = argparse.ArgumentParser(description='Modular Kubernetes Cluster Deployment')
    parser.add_argument('action', choices=['deploy', 'status', 'cleanup'], help='Action to perform')
    parser.add_argument('--profile', choices=[p.value for p in DeploymentProfile], 
                       help='Deployment profile')
    parser.add_argument('--components', nargs='+', choices=[c.value for c in Component],
                       help='Specific components to deploy')
    parser.add_argument('--config', help='Configuration file path')
    parser.add_argument('--force', action='store_true', help='Force redeploy existing components')
    
    args = parser.parse_args()
    
    orchestrator = ClusterDeploymentOrchestrator(args.config)
    
    if args.action == 'deploy':
        if args.profile:
            profile = DeploymentProfile(args.profile)
            success = orchestrator.deploy_profile(profile, args.force)
        elif args.components:
            components = [Component(c) for c in args.components]
            success = orchestrator.deploy_components(components, args.force)
        else:
            # Default to HA cluster
            success = orchestrator.deploy_profile(DeploymentProfile.HA_CLUSTER, args.force)
        
        sys.exit(0 if success else 1)
    
    elif args.action == 'status':
        orchestrator.status()
    
    elif args.action == 'cleanup':
        print("Cleanup functionality to be implemented")

if __name__ == "__main__":
    main()