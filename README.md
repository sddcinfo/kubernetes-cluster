# Enterprise Kubernetes on Proxmox VE

Production-grade automation framework for deploying highly available Kubernetes clusters on Proxmox VE infrastructure using industry-standard tooling and best practices.

## Overview

This solution provides comprehensive automation for deploying and managing production-ready Kubernetes clusters on Proxmox VE environments. Built using a proven technology stack of Packer, OpenTofu, Ansible, and Python, it eliminates manual configuration steps while ensuring consistent, reliable deployments.

**Note:** This solution requires VM templates (IDs 9000 and 9001) to be created first using the template-manager.py script from the ansible-provisioning-server repository.

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
| **VM Templates** | Cloud Images + virt-customize | Immutable VM template creation |
| **Infrastructure** | OpenTofu | Declarative infrastructure provisioning |
| **Kubernetes Deployment** | Kubespray v2.28.1+ | Production-ready cluster deployment |
| **Orchestration** | Python 3.11+ | Deployment coordination and state tracking |
| **Container Network** | Cilium 1.18.1 | eBPF-based CNI with advanced security and observability |
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
Control Plane VIP:    10.10.1.30
Control Plane Nodes:  10.10.1.31-33 (3 nodes)
Worker Nodes:         10.10.1.40-49 (10 IPs reserved, 4 initially deployed)
MetalLB Pool:         10.10.1.50-79 (30 IPs for LoadBalancer services)
Infrastructure:       10.10.1.80-89 (monitoring, logging, registry)
Future Expansion:     10.10.1.90-99
DHCP Range:           10.10.1.100-200 (unchanged, for dynamic clients)
```

For complete network allocation details, see [IP_ALLOCATION.md](docs/IP_ALLOCATION.md)

## Prerequisites

### Infrastructure Requirements

- **Proxmox VE 8.0+** cluster with minimum 4 nodes
- **Hardware per node**: 8+ CPU cores, 32GB+ RAM, 500GB+ storage
- **Storage**: Ceph RBD or similar distributed storage configured
- **Networking**: Bridge interface (vmbr0) configured for cluster traffic
- **DNS**: Forward and reverse DNS resolution configured

### Software Dependencies

```bash
# Install required packages on deployment host
sudo apt update
sudo apt install -y python3 python3-pip ansible packer kubectl

# Install OpenTofu (recommended over Terraform)
curl -sSL https://get.opentofu.org/install.sh | bash

# Foundation setup script uses only Python standard library (no additional dependencies needed)
```

### Proxmox Configuration

1. Create API tokens with appropriate permissions for automation
2. Configure storage pools (default: `rbd` for Ceph RBD)
3. Setup network bridges for cluster communication
4. Verify DNS resolution for external registries

## Deployment Process

### Phase-Based Deployment

The deployment follows a structured approach:

1. **Template Prerequisites** - Create VM templates using ansible-provisioning-server
2. **Environment Validation** - Verify prerequisites and connectivity  
3. **Infrastructure Provisioning** - Deploy VMs with OpenTofu
4. **Kubernetes Bootstrap** - Initialize cluster with kubeadm
5. **Platform Services** - Deploy monitoring, ingress, and storage

### Step 0: Setup and Create VM Templates (Required)

Before deploying the Kubernetes cluster, set up configuration and create templates:

```bash
# 1. Setup shared configuration (on ansible-provisioning-server host)
cd /path/to/ansible-provisioning-server
./scripts/bootstrap-config.sh

# 2. Create VM templates
python3 scripts/template-manager.py --create-templates

# 3. Verify templates are created
python3 scripts/template-manager.py --verify
```

This creates:
- Configuration at `~/proxmox-config/templates.yaml` (shared between repos)
- Template ID 9000: Ubuntu 24.04 base template  
- Template ID 9001: Ubuntu 24.04 with Kubernetes 1.33.4 pre-installed

### Quick Start

```bash
# Clone repository
git clone https://github.com/sddcinfo/kubernetes-cluster.git
cd kubernetes-cluster

# Phase 1-2: Foundation and template creation
python3 scripts/cluster-manager.py --setup-and-create

# Phase 3-5: Complete infrastructure and Kubernetes deployment
python3 scripts/deploy-dns-config.py          # Deploy DNS configuration
cd terraform && terraform apply               # Deploy VMs with OpenTofu
python3 scripts/deploy-kubespray-cluster.py   # Deploy Kubernetes with Kubespray
```

### Enhanced Fresh Cluster Deployment 🚀

**LATEST** - The deployment script now provides **component-specific deployment control** for maximum flexibility:

```bash
# Complete fresh deployment automation
python3 scripts/deploy-fresh-cluster.py

# Component-specific deployments
python3 scripts/deploy-fresh-cluster.py --infrastructure-only  # Deploy VMs only
python3 scripts/deploy-fresh-cluster.py --kubespray-only      # Setup Kubespray only  
python3 scripts/deploy-fresh-cluster.py --kubernetes-only     # Deploy K8s only

# Non-destructive verification
python3 scripts/deploy-fresh-cluster.py --verify-only         # Check VM status & SSH

# Advanced control flags
python3 scripts/deploy-fresh-cluster.py --skip-cleanup        # Skip VM cleanup phase
python3 scripts/deploy-fresh-cluster.py --skip-terraform-reset # Skip state reset
python3 scripts/deploy-fresh-cluster.py --force-recreate      # Force complete rebuild
```

**Key Features:**
- **Dynamic VM Detection** - Automatically reads placement from Terraform configuration
- **Component Isolation** - Deploy infrastructure, Kubespray, or Kubernetes independently  
- **Smart Verification** - Non-destructive status checking with SSH connectivity testing
- **Robust Error Handling** - Serial deployment with retry mechanisms for reliability
- **Download Optimization** - `download_run_once: true` with comprehensive caching

### Kubespray-Based Production Deployment

**SUCCESSFULLY IMPLEMENTED** - Uses **Kubespray v2.26.0** for production-ready clusters:

- **Kubernetes v1.30.4** - Deployed and validated stable version
- **Cilium v1.15.4** - Advanced eBPF networking with full functionality
- **Download Optimization** - Efficient caching and distribution across nodes
- **Automated HA Setup** - 3 control plane nodes with stacked etcd (fully operational)
- **Security Hardening** - Production security configurations applied
- **Repository Separation** - Kubespray downloaded as dependency, keeping repo clean
```

### 🚀 **100% Hands-Off Automation**

The cluster-manager now provides **completely automated template creation** with zero manual intervention:

```bash
# From clean slate to production-ready templates in ~4 minutes
python3 scripts/cluster-manager.py --setup-and-create

# Features:
# ✅ Automatic prerequisite validation
# ✅ Terraform user setup with proper permissions  
# ✅ Cloud image preparation with EFI boot support
# ✅ Base template creation (ubuntu-base-template, ID 9000)
# ✅ Kubernetes template with K8s v1.33.4 (ubuntu-k8s-template, ID 9001)
# ✅ Robust error handling and retry mechanisms
# ✅ Graceful VM management and template conversion
```

### Implementation Status

**COMPLETED**: All phases successfully implemented and tested.

The Kubernetes cluster deployment is fully operational with the following achievements:
- **Download Optimization**: `download_run_once: true` providing massive bandwidth savings
- **Repository Separation**: Kubespray downloaded as dependency, not committed to repo
- **7-Node Cluster**: Successfully deployed with 3 control plane + 4 workers
- **All Components Healthy**: Complete Kubernetes v1.30.4 with Cilium v1.15.4 networking
- **Production Ready**: Comprehensive configuration review completed and validated

For detailed implementation progress, see [STATUS.md](docs/STATUS.md)

### Component-Specific Deployment Workflow

The enhanced deployment script provides fine-grained control over deployment phases:

```bash
# Method 1: Step-by-step component deployment
python3 scripts/deploy-fresh-cluster.py --infrastructure-only    # Create VMs with Terraform
python3 scripts/deploy-fresh-cluster.py --verify-only           # Verify VM status & SSH
python3 scripts/deploy-fresh-cluster.py --kubespray-only        # Setup Kubespray environment
python3 scripts/deploy-fresh-cluster.py --kubernetes-only       # Deploy Kubernetes cluster

# Method 2: Single command deployment
python3 scripts/deploy-fresh-cluster.py                         # Complete automation

# Method 3: Skip phases for faster iteration
python3 scripts/deploy-fresh-cluster.py --skip-cleanup --skip-terraform-reset
```

**Verification and Troubleshooting:**
```bash
# Check VM status without any destructive actions
python3 scripts/deploy-fresh-cluster.py --verify-only

# Force complete rebuild from clean slate
python3 scripts/deploy-fresh-cluster.py --force-recreate

# View all available options
python3 scripts/deploy-fresh-cluster.py --help
```

### Legacy Individual Phase Execution

For granular control or troubleshooting using the original scripts:

```bash
# Phase 1: Foundation setup only
python3 scripts/cluster-manager.py --setup-foundation
# Phase 2: Template creation only (requires foundation)
python3 scripts/cluster-manager.py --create-templates
# Phase 3-5: Infrastructure and Kubernetes deployment
python3 scripts/deploy-dns-config.py          # Deploy DNS configuration
cd terraform && terraform apply               # Deploy VMs with OpenTofu
python3 scripts/deploy-kubespray-cluster.py   # Deploy Kubernetes with Kubespray
```

### Deployment Management

```bash
# Check deployment status
python3 cluster-deploy.py status

# Deploy single node cluster
python3 cluster-deploy.py deploy --profile single-node

# Deploy HA cluster (default)
python3 cluster-deploy.py deploy --profile ha-cluster

# Deploy specific components
python3 cluster-deploy.py deploy --components foundation template-manager infrastructure

# Force redeploy existing components
python3 cluster-deploy.py deploy --force

# Clean up all resources
python3 cluster-deploy.py cleanup
```

## Configuration

### Cluster Sizing

Edit configuration variables in phase scripts:

```bash
# scripts/03-provision-infrastructure.sh
CONTROL_NODES=3     # Control plane instances
WORKER_NODES=4      # Worker node count

# scripts/04-bootstrap-kubernetes.sh  
KUBE_VERSION="1.33.4"           # Kubernetes version
POD_NETWORK="10.244.0.0/16"     # Pod CIDR
SERVICE_NETWORK="10.96.0.0/12"  # Service CIDR
```

### DNS Configuration

The system uses a modular DNS approach:

```bash
# Deploy Kubernetes DNS configuration (coexists with existing infrastructure)
python3 scripts/deploy-dns-config.py
```

This creates DNS records for all Kubernetes components without affecting existing infrastructure. See [DNS_CONFIGURATION.md](docs/DNS_CONFIGURATION.md) for details.

### Proxmox Integration

Proxmox integration is handled by the cluster-manager.py script. The setup includes:
- Packer user creation with comprehensive permissions
- API token generation and management
- Cloud image preparation with qemu-guest-agent
- Template creation from cloud images

For manual configuration details, see `scripts/cluster-manager.py`.

## Documentation

This project includes comprehensive documentation:

- **[ARCHITECTURE.md](ARCHITECTURE.md)** - Technology selection and design decisions  
- **[docs/STATUS.md](docs/STATUS.md)** - Current implementation status and progress
- **[docs/IP_ALLOCATION.md](docs/IP_ALLOCATION.md)** - Complete network allocation strategy
- **[docs/DNS_CONFIGURATION.md](docs/DNS_CONFIGURATION.md)** - Modular DNS configuration approach
- **[docs/README.md](docs/README.md)** - Documentation index and navigation

See the [docs directory](docs/) for the complete documentation index.

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
python3 cluster-deploy.py cleanup  # Remove all resources
rm ~/.kube-cluster/cluster-state.json  # Clear deployment state
python3 cluster-deploy.py deploy   # Fresh deployment
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