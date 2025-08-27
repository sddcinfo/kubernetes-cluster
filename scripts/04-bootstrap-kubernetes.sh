#!/bin/bash
# Phase 4: Bootstrap Kubernetes Cluster with Ansible
# Initializes Kubernetes cluster with kubeadm

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
ANSIBLE_DIR="../ansible"
KUBE_VERSION="1.30.0"
POD_NETWORK="10.244.0.0/16"
SERVICE_NETWORK="10.96.0.0/12"
CONTROL_VIP="10.10.1.30"

echo "============================================================"
echo "PHASE 4: BOOTSTRAP KUBERNETES CLUSTER"
echo "============================================================"

# Function to print colored output
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

# Check if running from scripts directory
if [ ! -f "04-bootstrap-kubernetes.sh" ]; then
    log_error "Please run this script from the scripts directory"
    exit 1
fi

# Check for Ansible
if ! command -v ansible &> /dev/null; then
    log_error "Ansible not found. Please install Ansible."
    exit 1
fi

# Create Ansible playbook for Kubernetes bootstrap
log_info "Creating Ansible playbook..."
cat > "${ANSIBLE_DIR}/bootstrap-k8s.yml" << 'EOF'
---
- name: Bootstrap Kubernetes Cluster
  hosts: all
  become: yes
  gather_facts: yes
  
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

- name: Initialize first control plane node
  hosts: control_plane[0]
  become: yes
  vars:
    kubeadm_config: |
      apiVersion: kubeadm.k8s.io/v1beta3
      kind: InitConfiguration
      localAPIEndpoint:
        advertiseAddress: "{{ ansible_default_ipv4.address }}"
        bindPort: 6443
      ---
      apiVersion: kubeadm.k8s.io/v1beta3
      kind: ClusterConfiguration
      kubernetesVersion: v1.30.0
      controlPlaneEndpoint: "10.10.1.99:6443"
      networking:
        podSubnet: 10.244.0.0/16
        serviceSubnet: 10.96.0.0/12
      ---
      apiVersion: kubelet.config.k8s.io/v1beta1
      kind: KubeletConfiguration
      cgroupDriver: systemd
  
  tasks:
    - name: Check if cluster is already initialized
      stat:
        path: /etc/kubernetes/admin.conf
      register: kubeadm_init
    
    - name: Create kubeadm config file
      copy:
        content: "{{ kubeadm_config }}"
        dest: /tmp/kubeadm-config.yaml
      when: not kubeadm_init.stat.exists
    
    - name: Initialize Kubernetes cluster
      command: kubeadm init --config=/tmp/kubeadm-config.yaml --upload-certs
      register: kubeadm_init_output
      when: not kubeadm_init.stat.exists
    
    - name: Create .kube directory for ubuntu user
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
    
    - name: Get join command for control plane
      shell: kubeadm token create --print-join-command --certificate-key $(kubeadm init phase upload-certs --upload-certs | grep -v upload-certs)
      register: control_plane_join_command
      when: not kubeadm_init.stat.exists
    
    - name: Get join command for workers
      command: kubeadm token create --print-join-command
      register: worker_join_command
    
    - name: Store join commands
      set_fact:
        control_join: "{{ control_plane_join_command.stdout if not kubeadm_init.stat.exists else '' }}"
        worker_join: "{{ worker_join_command.stdout }}"

- name: Join additional control plane nodes
  hosts: control_plane[1:]
  become: yes
  tasks:
    - name: Check if already joined
      stat:
        path: /etc/kubernetes/kubelet.conf
      register: kubelet_conf
    
    - name: Join control plane
      command: "{{ hostvars[groups['control_plane'][0]]['control_join'] }}"
      when: 
        - not kubelet_conf.stat.exists
        - hostvars[groups['control_plane'][0]]['control_join'] != ''

- name: Join worker nodes
  hosts: workers
  become: yes
  tasks:
    - name: Check if already joined
      stat:
        path: /etc/kubernetes/kubelet.conf
      register: kubelet_conf
    
    - name: Join cluster as worker
      command: "{{ hostvars[groups['control_plane'][0]]['worker_join'] }}"
      when: not kubelet_conf.stat.exists

- name: Configure kubectl and install CNI
  hosts: control_plane[0]
  become: yes
  become_user: ubuntu
  tasks:
    - name: Wait for nodes to be ready
      shell: kubectl get nodes
      register: nodes_status
      until: nodes_status.rc == 0
      retries: 10
      delay: 30
    
    - name: Install Cilium CLI
      shell: |
        CILIUM_CLI_VERSION=$(curl -s https://raw.githubusercontent.com/cilium/cilium-cli/main/stable.txt)
        CLI_ARCH=amd64
        if [ "$(uname -m)" = "aarch64" ]; then CLI_ARCH=arm64; fi
        curl -L --fail --remote-name-all https://github.com/cilium/cilium-cli/releases/download/${CILIUM_CLI_VERSION}/cilium-linux-${CLI_ARCH}.tar.gz{,.sha256sum}
        sha256sum --check cilium-linux-${CLI_ARCH}.tar.gz.sha256sum
        sudo tar xzvfC cilium-linux-${CLI_ARCH}.tar.gz /usr/local/bin
        rm cilium-linux-${CLI_ARCH}.tar.gz{,.sha256sum}
      args:
        creates: /usr/local/bin/cilium
    
    - name: Install Cilium CNI
      shell: cilium install --version 1.15.0
      register: cilium_install
      changed_when: "'Cilium was successfully installed' in cilium_install.stdout"
    
    - name: Wait for Cilium to be ready
      shell: cilium status --wait
      register: cilium_status
      until: cilium_status.rc == 0
      retries: 20
      delay: 30
    
    - name: Get cluster status
      command: kubectl get nodes -o wide
      register: cluster_nodes
    
    - name: Display cluster status
      debug:
        msg: "{{ cluster_nodes.stdout_lines }}"
EOF

# Create HAProxy configuration for control plane load balancing
log_info "Creating HAProxy configuration for HA control plane..."
cat > "${ANSIBLE_DIR}/haproxy-setup.yml" << 'EOF'
---
- name: Setup HAProxy for Control Plane HA
  hosts: control_plane[0]
  become: yes
  
  tasks:
    - name: Install HAProxy and Keepalived
      apt:
        name:
          - haproxy
          - keepalived
        state: present
        update_cache: yes
    
    - name: Configure HAProxy
      copy:
        content: |
          global
              log /dev/log local0
              chroot /var/lib/haproxy
              stats socket /run/haproxy/admin.sock mode 660 level admin
              stats timeout 30s
              user haproxy
              group haproxy
              daemon
          
          defaults
              log     global
              mode    tcp
              option  tcplog
              option  dontlognull
              timeout connect 5000
              timeout client  50000
              timeout server  50000
          
          frontend kubernetes-frontend
              bind *:6443
              mode tcp
              option tcplog
              default_backend kubernetes-backend
          
          backend kubernetes-backend
              mode tcp
              option tcp-check
              balance roundrobin
              server control-1 10.10.1.100:6443 check
              server control-2 10.10.1.101:6443 check
              server control-3 10.10.1.102:6443 check
        dest: /etc/haproxy/haproxy.cfg
      notify: restart haproxy
    
    - name: Configure Keepalived
      copy:
        content: |
          vrrp_instance VI_1 {
              state MASTER
              interface eth0
              virtual_router_id 51
              priority 100
              advert_int 1
              authentication {
                  auth_type PASS
                  auth_pass k8s_pass
              }
              virtual_ipaddress {
                  10.10.1.99/24
              }
          }
        dest: /etc/keepalived/keepalived.conf
      notify: restart keepalived
  
  handlers:
    - name: restart haproxy
      systemd:
        name: haproxy
        state: restarted
    
    - name: restart keepalived
      systemd:
        name: keepalived
        state: restarted
EOF

# Check inventory file
if [ ! -f "${ANSIBLE_DIR}/inventory.yml" ]; then
    log_error "Ansible inventory not found. Please run Phase 3 first."
    exit 1
fi

# Test Ansible connectivity
log_info "Testing Ansible connectivity to all nodes..."
if ansible -i "${ANSIBLE_DIR}/inventory.yml" all -m ping > /dev/null 2>&1; then
    log_info "All nodes are reachable via Ansible"
else
    log_error "Some nodes are not reachable. Please check connectivity."
    exit 1
fi

# Run HAProxy setup for HA (optional)
log_info "Setting up HAProxy for control plane HA..."
ansible-playbook -i "${ANSIBLE_DIR}/inventory.yml" "${ANSIBLE_DIR}/haproxy-setup.yml"

# Bootstrap Kubernetes cluster
log_info "Bootstrapping Kubernetes cluster..."
log_info "This may take 10-15 minutes..."

if ansible-playbook -i "${ANSIBLE_DIR}/inventory.yml" "${ANSIBLE_DIR}/bootstrap-k8s.yml"; then
    log_info "Kubernetes cluster bootstrapped successfully!"
    
    # Copy kubeconfig to local machine
    log_info "Copying kubeconfig to local machine..."
    mkdir -p ~/.kube
    scp ubuntu@10.10.1.100:/home/ubuntu/.kube/config ~/.kube/config-k8s-cluster
    
    # Set KUBECONFIG
    export KUBECONFIG=~/.kube/config-k8s-cluster
    
    # Verify cluster
    log_info "Verifying cluster status..."
    kubectl get nodes
    kubectl get pods -A
    
    echo ""
    echo "============================================================"
    echo -e "${GREEN}✓ PHASE 4 COMPLETED SUCCESSFULLY${NC}"
    echo "Kubernetes cluster is ready!"
    echo ""
    echo "To access the cluster:"
    echo "  export KUBECONFIG=~/.kube/config-k8s-cluster"
    echo "  kubectl get nodes"
    echo ""
    echo "Proceed to Phase 5: Deploy Platform Services"
    echo "============================================================"
else
    log_error "Kubernetes bootstrap failed"
    exit 1
fi