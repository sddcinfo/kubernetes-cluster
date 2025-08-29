# Kubernetes Cluster Automation

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-1.30.4-326CE5?logo=kubernetes&logoColor=white)](https://kubernetes.io/)
[![Kubespray](https://img.shields.io/badge/Kubespray-2.28.1-FF6B35)](https://kubespray.io/)
[![Proxmox](https://img.shields.io/badge/Proxmox_VE-8.0+-E57000?logo=proxmox&logoColor=white)](https://www.proxmox.com/)

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

**Important**: This solution requires VM templates (IDs 9000 and 9001) to be created first using the [ansible-provisioning-server](https://github.com/sddcinfo/ansible-provisioning-server) repository.

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
| **Infrastructure** | OpenTofu | 1.7+ | Declarative infrastructure provisioning |
| **Kubernetes** | Kubespray | 2.28.1 | Production-ready cluster deployment |
| **Container Network** | Cilium | 1.17+ | eBPF-based CNI with advanced networking and security |
| **Storage** | Proxmox CSI | Latest | Dynamic persistent volume provisioning |
| **Load Balancing** | MetalLB | Latest | Bare-metal LoadBalancer implementation |
| **Orchestration** | Python | 3.11+ | Deployment coordination and automation |

## Architecture

### Cluster Design

The solution deploys a production-grade Kubernetes cluster with the following topology:

- **Control Plane**: 3 nodes with stacked etcd for high availability
- **Worker Nodes**: 4+ nodes with configurable scaling
- **Load Balancer**: HAProxy + Keepalived for control plane access
- **Network**: Cilium CNI with eBPF dataplane and optional BGP
- **Storage**: Proxmox CSI with Ceph RBD integration

### Network Topology

```
Network: 10.10.1.0/24 | Gateway: 10.10.1.1 | Domain: sddc.info

Infrastructure Services     (10.10.1.1-29)
├── 10.10.1.1               gateway.sddc.info (DNS/DHCP)
└── 10.10.1.21-24           node1-4 (Proxmox hypervisors)

Kubernetes Cluster         (10.10.1.30-99)
├── Control Plane          (10.10.1.30-39)
│   ├── 10.10.1.30          k8s-vip (Virtual IP)
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

- **Proxmox VE**: Version 8.0+ cluster with minimum 4 nodes
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
- **Template 9000**: Ubuntu 24.04 base template
- **Template 9001**: Ubuntu 24.04 with Kubernetes runtime

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
| 10.10.1.30 | Control Plane VIP | k8s-vip.sddc.info |
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

## Operations

### Cluster Access

```bash
# Configure kubectl access
export KUBECONFIG=~/.kube/config-k8s-cluster
kubectl get nodes
```

### Management Interfaces

**Kubernetes Dashboard**
```bash
kubectl proxy
# Access: http://localhost:8001/api/v1/namespaces/kubernetes-dashboard/services/https:kubernetes-dashboard:/proxy/
```

**Grafana Monitoring**
```bash
kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80
# Access: http://localhost:3000 (admin/admin)
```

**Prometheus Metrics**
```bash
kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090
# Access: http://localhost:9090
```

**Cilium Hubble UI**
```bash
kubectl port-forward -n kube-system svc/hubble-ui 12000:80
# Access: http://localhost:12000
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