# Kubernetes Cluster Automation

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-1.33+-326CE5?logo=kubernetes&logoColor=white)](https://kubernetes.io/)
[![Kubespray](https://img.shields.io/badge/Kubespray-Latest-FF6B35)](https://kubespray.io/)
[![Proxmox](https://img.shields.io/badge/Proxmox_VE-9.0+-E57000?logo=proxmox&logoColor=white)](https://www.proxmox.com/)

Production-grade automation framework for deploying highly available Kubernetes clusters on Proxmox VE infrastructure using industry-standard tooling and best practices.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Network Configuration](#network-configuration)
- [Deployment Options](#deployment-options)
- [Configuration](#configuration)
- [Operations](#operations)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

## Overview

This solution provides comprehensive automation for deploying and managing production-ready Kubernetes clusters on Proxmox VE environments. Built using a proven technology stack of OpenTofu, Kubespray, and Python, it eliminates manual configuration steps while ensuring consistent, reliable deployments.

**Important**: This solution requires a VM template (ID 9000) to be created first using the [ansible-provisioning-server](https://github.com/sddcinfo/ansible-provisioning-server) repository.

### Key Features

- **Zero-Touch Deployment**: Fully automated cluster provisioning from infrastructure to platform services
- **High Availability**: Multi-master control plane with integrated load balancing
- **Production Hardening**: Security best practices and enterprise-grade configurations
- **Scalable Architecture**: Easy horizontal scaling with automated node management
- **Infrastructure as Code**: Version-controlled, repeatable deployments with state management
- **Comprehensive Monitoring**: Integrated observability stack with Prometheus and Grafana

### Technology Stack

| Component | Technology | Version | Purpose |
|-----------|------------|---------|---------|
| **Infrastructure** | OpenTofu | Latest | Declarative infrastructure provisioning |
| **Kubernetes** | Kubespray | Latest | Production-ready cluster deployment |
| **Container Network** | Cilium | Latest | eBPF-based CNI with advanced networking and security |
| **Storage** | Proxmox CSI | Latest | Dynamic persistent volume provisioning |
| **Load Balancing** | MetalLB | Latest | Bare-metal LoadBalancer implementation |
| **Orchestration** | Python | 3.11+ | Deployment coordination and automation |

## Architecture

### Cluster Design

The solution deploys a production-grade Kubernetes cluster with the following topology:

- **Control Plane**: 3 nodes with stacked etcd for high availability
- **Worker Nodes**: 4+ nodes with configurable scaling
- **Load Balancer**: HAProxy for control plane access
- **Network**: Cilium CNI with eBPF dataplane and optional BGP
- **Storage**: Proxmox CSI with Ceph RBD integration

### Network Topology

```
Network: 10.10.1.0/24 | Gateway: 10.10.1.1 | Domain: sddc.info

Infrastructure Services     (10.10.1.1-29)
├── 10.10.1.1               gateway.sddc.info (DNS/DHCP)
└── 10.10.1.21-24           node1-4 (Proxmox hypervisors)

Kubernetes Cluster         (10.10.1.30-99)
├── Load Balancer          (10.10.1.30)
│   └── 10.10.1.30          k8s-vip.sddc.info (HAProxy LB for API)
├── Control Plane          (10.10.1.31-39)
│   └── 10.10.1.31-33       k8s-control-1 through k8s-control-3
├── Worker Nodes           (10.10.1.40-49)
│   ├── 10.10.1.40-43       k8s-worker-1 through k8s-worker-4
│   └── 10.10.1.44-49       Reserved for scaling
├── MetalLB Pool           (10.10.1.50-79)
├── Infrastructure         (10.10.1.80-89)
└── Future Expansion       (10.10.1.90-99)

DHCP Range                 (10.10.1.100-200)
```

## Prerequisites

### Infrastructure Requirements

- **Proxmox VE**: Version 9.0+ cluster with minimum 4 nodes
- **Hardware**: 8+ CPU cores, 32GB+ RAM, 500GB+ storage per node
- **Storage**: Ceph RBD or distributed storage backend
- **Network**: Bridge interface (vmbr0) for cluster communication
- **DNS**: Forward and reverse DNS resolution configured

### Software Dependencies

```bash
# Install required packages on deployment host
sudo apt update
sudo apt install -y python3 python3-pip ansible kubectl

# Install OpenTofu (recommended over Terraform)
curl -sSL https://get.opentofu.org/install.sh | bash
```

### VM Templates

Create required templates using the ansible-provisioning-server repository:

```bash
# On ansible-provisioning-server host
cd /path/to/ansible-provisioning-server
python3 scripts/template-manager.py --create-templates
```

This creates:
- **Template 9000**: Ubuntu 24.04 base template with cloud-init and qemu-guest-agent

## Quick Start

```bash
# Clone repository
git clone https://github.com/sddcinfo/kubernetes-cluster.git
cd kubernetes-cluster

# Deploy complete cluster
python3 scripts/deploy-fresh-cluster.py
```

## Network Configuration

### DNS Configuration

Deploy Kubernetes-specific DNS records:

```bash
python3 scripts/deploy-dns-config.py
```

This creates DNS entries for:
- Control plane nodes and virtual IP
- Worker nodes
- Service endpoints (ingress, monitoring, registry)
- Wildcard DNS for applications (*.apps.sddc.info)

### IP Allocation

The system uses a structured IP allocation strategy:

| Range | Purpose | Example |
|-------|---------|---------|
| 10.10.1.30 | HAProxy Load Balancer | k8s-vip.sddc.info |
| 10.10.1.31-33 | Control Plane Nodes | k8s-control-1.sddc.info |
| 10.10.1.40-49 | Worker Nodes | k8s-worker-1.sddc.info |
| 10.10.1.50-79 | MetalLB LoadBalancer Pool | ingress.k8s.sddc.info |

## Deployment Options

### Complete Deployment

```bash
# Full cluster deployment with all phases
python3 scripts/deploy-fresh-cluster.py
```

### Component-Specific Deployment

```bash
# Infrastructure only (VMs with OpenTofu)
python3 scripts/deploy-fresh-cluster.py --infrastructure-only

# Kubespray environment setup
python3 scripts/deploy-fresh-cluster.py --kubespray-only

# Kubernetes cluster deployment
python3 scripts/deploy-fresh-cluster.py --kubernetes-only

# Verification without changes
python3 scripts/deploy-fresh-cluster.py --verify-only
```

### Advanced Options

```bash
# Skip cleanup phase
python3 scripts/deploy-fresh-cluster.py --skip-cleanup

# Skip Terraform state reset
python3 scripts/deploy-fresh-cluster.py --skip-terraform-reset

# Force complete rebuild
python3 scripts/deploy-fresh-cluster.py --force-recreate

# Fast mode for re-runs (5-15 minutes instead of 15-30 minutes)
python3 scripts/deploy-fresh-cluster.py --kubernetes-only --fast
```

## Configuration

### Cluster Sizing

Edit Terraform variables to adjust cluster size:

```bash
# terraform/terraform.tfvars
control_plane_nodes = 3     # Control plane instances
worker_nodes = 4            # Worker node count
```

### Kubespray Configuration

Generate Kubespray inventory:

```bash
python3 scripts/generate-kubespray-inventory.py
```

This creates optimized inventory configuration with:
- Node role assignments
- Network configuration
- Performance optimizations
- Security hardening

## High Availability Optimization

### HA Mode Selection

The deployment script supports **3 optimized HA modes** for different use cases:

```bash
# Localhost HA (default, recommended) - built-in nginx on worker nodes
python3 scripts/deploy-fresh-cluster.py --ha-mode localhost

# Kube-VIP HA - modern cloud-native VIP with leader election  
python3 scripts/deploy-fresh-cluster.py --ha-mode kube-vip

# External HA - legacy HAProxy approach (not recommended)
python3 scripts/deploy-fresh-cluster.py --ha-mode external
```

### HA Mode Comparison

| Mode | Performance | Complexity | Certificate Issues | Infrastructure |
|------|-------------|------------|-------------------|----------------|
| **localhost** | High | Simple | None | Built-in |
| **kube-vip** | Highest | Moderate | None | Cloud-native |
| **external** | Low | Complex | SAN issues | Extra VM |

**Recommended Approach:**
- **Default**: Use `localhost` mode (built-in nginx proxy)
- **Advanced**: Use `kube-vip` mode for true VIP with leader election
- **Legacy**: Avoid `external` mode unless required for specific setups

### Localhost HA (Recommended)
- **Zero configuration** - works out of the box
- **High performance** - nginx proxy on each worker node  
- **No certificate issues** - properly integrated
- **Fault tolerant** - if one worker fails, others provide access
- **Zero infrastructure overhead** - no additional VMs needed

### Kube-VIP HA (Advanced)
- **True VIP** - single IP address (10.10.1.30)
- **Leader election** - automatic failover between control nodes
- **IPVS performance** - high-performance load balancing
- **Certificate compatible** - VIP included in certificate SAN
- **Network configuration** - requires careful interface setup

## Performance Optimization

### Fast Mode for Re-deployments

The deployment script includes a **fast mode** specifically optimized for re-running Kubespray on existing clusters:

```bash
# Fast re-deployment (5-15 minutes vs 15-30 minutes)
python3 scripts/deploy-fresh-cluster.py --kubernetes-only --fast
```

**Fast Mode Optimizations:**

- **Skip Downloads**: Uses cached container images and binaries
- **Skip OS Bootstrap**: Skips system package updates and OS configuration  
- **Optimized Tags**: Uses selective Ansible tags (`k8s-cluster,network,master,node,addons`)
- **Skip Initialization**: Skips `download`, `bootstrap-os`, and `preinstall` tags
- **Enhanced Ansible Config**: 
  - SSH connection multiplexing with ControlMaster
  - Increased parallelism (20 forks)
  - Smart fact gathering with memory caching
  - Performance profiling enabled

**When to Use Fast Mode:**
- Re-running deployment on existing infrastructure
- Applying configuration changes to running cluster
- Testing deployment modifications quickly
- First-time deployments (use standard mode)
- Major version upgrades (use standard mode)

**Performance Comparison:**
- **Standard Mode**: 15-30 minutes (full deployment)
- **Fast Mode**: 5-15 minutes (optimized re-run)
- **Time Savings**: 50-70% reduction in deployment time

## Applications Deployment

### Monitoring and Observability Stack

Deploy comprehensive monitoring with Prometheus, Grafana, and persistent storage:

```bash
# Deploy complete applications stack (storage + monitoring)
python3 scripts/deploy-applications.py

# Deploy only storage integration
python3 scripts/deploy-applications.py --storage-only

# Deploy only monitoring stack
python3 scripts/deploy-applications.py --monitoring-only

# Verify existing deployments
python3 scripts/deploy-applications.py --verify-only
```

### Applications Architecture

**Storage Integration:**
- **Proxmox CSI Plugin** - Dynamic persistent volume provisioning
- **Ceph RBD Integration** - Distributed storage backend
- **Storage Classes**: `proxmox-rbd` (default), `proxmox-rbd-fast`

**Monitoring Stack:**
- **Prometheus** - Metrics collection and storage (100Gi persistent storage)
- **Grafana** - Visualization dashboards with LoadBalancer (10.10.1.50)
- **AlertManager** - Alert processing and notifications
- **Proxmox Exporter** - Infrastructure metrics collection

**Key Features:**
- **Persistent Storage** - All monitoring components use Proxmox Ceph RBD
- **High Availability** - Prometheus and AlertManager with 2 replicas
- **LoadBalancer Integration** - Grafana accessible via MetalLB (10.10.1.50)
- **Custom Dashboards** - Kubernetes cluster, Proxmox infrastructure, and Ceph storage
- **Automated Discovery** - ServiceMonitor integration for metrics collection

### Applications Access

**Grafana Dashboard:**
- URL: http://10.10.1.50/ (LoadBalancer IP)
- Username: `admin`
- Password: `kubernetes-admin-2024`

**Prometheus Metrics:**
```bash
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090
# Access: http://localhost:9090
```

**AlertManager:**
```bash  
kubectl port-forward -n monitoring svc/kube-prometheus-stack-alertmanager 9093:9093
# Access: http://localhost:9093
```

### Storage Testing

Test persistent volume provisioning:

```bash
# Create test PVC
kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: test-pvc
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 1Gi
EOF

# Verify PVC is bound
kubectl get pvc test-pvc

# Cleanup
kubectl delete pvc test-pvc
```

## Operations

## Cluster Status and Access

### Cluster Access

```bash
# Direct connection to control plane
export KUBECONFIG=~/.kube/config-direct
kubectl get nodes

# Direct connection works without certificate issues
kubectl get nodes

# Cluster information
kubectl cluster-info
```

### Management Interfaces

**Grafana Monitoring Dashboard** (Primary)
- Direct LoadBalancer Access: http://10.10.1.50/
- Username: `admin` / Password: `kubernetes-admin-2024`
- Features: Kubernetes cluster metrics, Proxmox infrastructure, Ceph storage

**Prometheus Metrics**
```bash
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090
# Access: http://localhost:9090
```

**AlertManager**
```bash
kubectl port-forward -n monitoring svc/kube-prometheus-stack-alertmanager 9093:9093
# Access: http://localhost:9093
```

**Cilium Hubble UI**
```bash
kubectl port-forward -n kube-system svc/hubble-ui 12000:80
# Access: http://localhost:12000
```

**Kubernetes Dashboard** (Optional)
```bash
kubectl proxy
# Access: http://localhost:8001/api/v1/namespaces/kubernetes-dashboard/services/https:kubernetes-dashboard:/proxy/
```

### Scaling Operations

```bash
# Scale worker nodes
vim terraform/terraform.tfvars  # Update worker_nodes count
cd terraform && tofu apply

# Add nodes to cluster
kubectl get nodes
```

## Troubleshooting

### Common Issues

**Infrastructure Provisioning Failures**
```bash
cd terraform
tofu show                    # Review current state
tofu plan                    # Verify planned changes
tofu destroy --auto-approve  # Clean slate if needed
```

**Cluster Bootstrap Problems**
```bash
# Check node connectivity
ansible -i kubespray/inventory/proxmox-cluster/inventory.ini all -m ping

# Verify Kubernetes status
kubectl get nodes
kubectl get pods --all-namespaces
```

**Service Deployment Issues**
```bash
# Check cluster DNS
kubectl get pods -n kube-system -l k8s-app=kube-dns

# Verify storage class
kubectl get storageclass

# Review resource constraints
kubectl describe nodes
```

### Recovery Procedures

**Complete Environment Reset**
```bash
python3 scripts/deploy-fresh-cluster.py --force-recreate
```

**Partial Recovery**
```bash
# Infrastructure only
python3 scripts/deploy-fresh-cluster.py --infrastructure-only

# Kubernetes only
python3 scripts/deploy-fresh-cluster.py --kubernetes-only
```

### Logs and Diagnostics

**Deployment Logs**
```bash
# View deployment output
python3 scripts/deploy-fresh-cluster.py --verify-only

# Check Terraform state
cd terraform && tofu show
```

**Cluster Diagnostics**
```bash
# Node status
kubectl get nodes -o wide

# System pods
kubectl get pods -n kube-system

# Cluster events
kubectl get events --all-namespaces
```

## Contributing

We welcome contributions to improve this automation framework. Please follow these guidelines:

### Development Setup

```bash
# Clone repository
git clone https://github.com/sddcinfo/kubernetes-cluster.git
cd kubernetes-cluster

# Create feature branch
git checkout -b feature/your-enhancement
```

### Testing

Before submitting changes:

1. Test deployment in isolated environment
2. Verify all phases complete successfully
3. Validate cluster functionality
4. Update documentation as needed

### Pull Request Process

1. Create descriptive commit messages
2. Update README for significant changes
3. Test deployment scenarios
4. Submit pull request with detailed description

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

## Support

For technical support and questions:

- **Issues**: [GitHub Issues](https://github.com/sddcinfo/kubernetes-cluster/issues)
- **Documentation**: This README and inline code documentation
- **Community**: Join discussions in project issues

---

**Kubernetes Cluster Automation** - Production-ready infrastructure automation for modern container orchestration.