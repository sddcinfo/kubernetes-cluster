# Enterprise Kubernetes on Proxmox VE

Production-grade automation framework for deploying highly available Kubernetes clusters on Proxmox VE infrastructure using industry-standard tooling and best practices.

## Overview

This solution provides comprehensive automation for deploying and managing production-ready Kubernetes clusters on Proxmox VE environments. Built using a proven technology stack of Packer, OpenTofu, Ansible, and Python, it eliminates manual configuration steps while ensuring consistent, reliable deployments.

### Key Features

- **Zero-touch deployment** - Fully automated cluster provisioning from bare infrastructure
- **High availability** - Multi-master control plane with load balancer and keepalived
- **Production hardening** - Security best practices, monitoring, and backup solutions
- **Scalable architecture** - Easy horizontal scaling of worker nodes
- **Infrastructure as Code** - Version-controlled, repeatable deployments
- **Comprehensive monitoring** - Prometheus, Grafana, and alerting stack included

### Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Golden Images** | HashiCorp Packer | Immutable VM template creation |
| **Infrastructure** | OpenTofu | Declarative infrastructure provisioning |
| **Configuration** | Ansible | Idempotent configuration management |
| **Orchestration** | Python 3.11+ | Deployment coordination and state tracking |
| **Container Network** | Cilium | eBPF-based CNI with security policies |
| **Storage** | Proxmox CSI | Dynamic persistent volume provisioning |
| **Load Balancing** | MetalLB | Bare-metal LoadBalancer service implementation |

## Architecture

The solution deploys a production-grade Kubernetes cluster with the following components:

- **3 Control Plane Nodes** - High availability with stacked etcd
- **4+ Worker Nodes** - Configurable based on workload requirements  
- **HAProxy + Keepalived** - Control plane load balancing and VIP management
- **Cilium CNI** - Advanced networking with eBPF dataplane
- **Proxmox CSI** - Integration with Ceph storage backend
- **Platform Services** - Ingress, monitoring, backup, and certificate management

### Network Configuration

```
Control Plane VIP:    10.10.1.99
Control Plane Nodes:  10.10.1.100-102
Worker Nodes:         10.10.1.110-113
MetalLB IP Pool:      10.10.1.150-180
```

## Prerequisites

### Infrastructure Requirements

- **Proxmox VE 8.0+** cluster with minimum 4 nodes
- **Hardware per node**: 8+ CPU cores, 32GB+ RAM, 500GB+ storage
- **Storage**: Ceph RBD or similar distributed storage configured
- **Networking**: Dedicated bridge interface (vmbr1) configured
- **DNS**: Forward and reverse DNS resolution configured

### Software Dependencies

```bash
# Install required packages on deployment host
sudo apt update
sudo apt install -y python3 python3-pip ansible packer kubectl

# Install OpenTofu (recommended over Terraform)
curl -sSL https://get.opentofu.org/install.sh | bash

# Install Python dependencies
pip3 install -r requirements.txt
```

### Proxmox Configuration

1. Create API tokens with appropriate permissions for automation
2. Configure storage pools (default: `rbd` for Ceph RBD)
3. Setup network bridges for cluster communication
4. Verify DNS resolution for external registries

## Deployment Process

### Phase-Based Deployment

The deployment follows a structured 5-phase approach:

1. **Environment Validation** - Verify prerequisites and connectivity
2. **Golden Image Creation** - Build Kubernetes-ready VM templates  
3. **Infrastructure Provisioning** - Deploy VMs with OpenTofu
4. **Kubernetes Bootstrap** - Initialize cluster with kubeadm
5. **Platform Services** - Deploy monitoring, ingress, and storage

### Quick Start

```bash
# Clone repository
git clone https://github.com/sddcinfo/kubernetes-cluster.git
cd kubernetes-cluster

# Configure deployment settings
vim terraform/terraform.tfvars  # Update Proxmox connection details

# Execute full deployment
cd scripts
python3 deploy-cluster.py deploy
```

### Current Status

**Phase 1 ✅ COMPLETED** - Environment validation with RBD storage support  
**Phase 2 ✅ COMPLETED** - Ubuntu 24.04 golden image with EFI boot and qemu-guest-agent  
**Phase 3 🔄 READY** - Infrastructure provisioning with OpenTofu  
**Phase 4 🔄 READY** - Kubernetes bootstrap with kubeadm  
**Phase 5 🔄 READY** - Platform services deployment  

Working golden template: `ubuntu-2404-golden` (VM ID: 9001) on Proxmox

### Individual Phase Execution

For granular control or troubleshooting:

```bash
cd scripts

# Phase 1: Environment validation
python3 01-validate-environment.py

# Phase 2: Golden image creation (includes cloud image preparation)
./prepare-cloud-image.sh      # Prepare Ubuntu cloud image with qemu-guest-agent
./02-build-golden-image.sh     # Create base template for Packer
packer build ../packer/ubuntu-golden.pkr.hcl  # Build golden template

# Phase 3-5: Infrastructure and Kubernetes deployment
./03-provision-infrastructure.sh  
./04-bootstrap-kubernetes.sh
./05-deploy-platform-services.sh
```

### Deployment Management

```bash
# Check deployment status
python3 deploy-cluster.py status

# Skip completed phases
python3 deploy-cluster.py deploy --skip-phases VALIDATE BUILD_IMAGE

# Force complete rebuild
python3 deploy-cluster.py deploy --force-rebuild

# Clean up all resources
python3 deploy-cluster.py cleanup
```

## Configuration

### Cluster Sizing

Edit configuration variables in phase scripts:

```bash
# scripts/03-provision-infrastructure.sh
CONTROL_NODES=3     # Control plane instances
WORKER_NODES=4      # Worker node count

# scripts/04-bootstrap-kubernetes.sh  
KUBE_VERSION="1.30.0"           # Kubernetes version
POD_NETWORK="10.244.0.0/16"     # Pod CIDR
SERVICE_NETWORK="10.96.0.0/12"  # Service CIDR
```

### Proxmox Integration

Update connection parameters in `terraform/main.tf`:

```hcl
variable "proxmox_host" {
  default = "10.10.1.21"
}

variable "proxmox_token" {
  default = "automation@pam!deploy=<token-secret>"
}
```

## Cluster Access

### kubectl Configuration

```bash
# Configure local access
export KUBECONFIG=~/.kube/config-k8s-cluster
kubectl get nodes
kubectl get pods --all-namespaces
```

### Management Interfaces

**Kubernetes Dashboard**
```bash
kubectl proxy
# Access: http://localhost:8001/api/v1/namespaces/kubernetes-dashboard/services/https:kubernetes-dashboard:/proxy/
# Token: cat manifests/monitoring/dashboard-token.txt
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

## Operations

### Scaling Workers

```bash
# Update worker count
vim scripts/03-provision-infrastructure.sh  # Increase WORKER_NODES
cd terraform && tofu apply
```

### Backup Management

Velero backup system is configured for:
- Cluster state and configuration
- Persistent volume snapshots  
- Application-level backup scheduling

### Monitoring and Alerting

Pre-configured monitoring stack includes:
- **Prometheus** - Metrics collection and alerting
- **Grafana** - Visualization and dashboards
- **AlertManager** - Alert routing and notification
- **Node Exporter** - Hardware and OS metrics

## Troubleshooting

### Deployment Issues

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
ansible -i ansible/inventory.yml all -m ping

# Verify Kubernetes prerequisites
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
python3 deploy-cluster.py cleanup  # Remove all resources
python3 deploy-cluster.py reset    # Clear deployment state
python3 deploy-cluster.py deploy   # Fresh deployment
```

## Production Considerations

### Security Hardening
- RBAC enabled by default with principle of least privilege
- Network policies enforced via Cilium
- Pod security policies implemented
- Regular security updates via automated patching

### Backup Strategy  
- Automated daily cluster state backups via Velero
- Persistent volume snapshot scheduling
- Disaster recovery procedures documented
- Regular backup restoration testing

### Performance Optimization
- Resource requests and limits configured
- Horizontal Pod Autoscaler (HPA) enabled
- Cluster monitoring and capacity planning
- Network performance tuning for high-throughput workloads

## Support

For technical issues or deployment assistance:

1. Review deployment logs in `scripts/deployment-state.json`
2. Consult [ARCHITECTURE.md](ARCHITECTURE.md) for design decisions
3. Check Proxmox and Kubernetes documentation for component-specific issues
4. Engage enterprise support channels for production environments

---

**Enterprise Kubernetes on Proxmox VE** - Production-ready automation for modern infrastructure.