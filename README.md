# Kubernetes on Proxmox - Production-Ready Automation

Complete automation framework for deploying production-grade Kubernetes clusters on Proxmox VE using industry best practices.

## Quick Start

```bash
# Clone the repository
git clone https://github.com/yourusername/kubernetes-cluster.git
cd kubernetes-cluster/scripts

# Deploy complete cluster
python3 deploy-cluster.py deploy

# Check status
python3 deploy-cluster.py status
```

## Architecture Overview

This solution implements a **5-phase deployment approach** using proven tools:

- **Packer** - VM golden image creation
- **OpenTofu/Terraform** - Infrastructure as Code
- **Ansible** - Configuration management
- **Python** - Orchestration and automation

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed design decisions.

## Prerequisites

### Hardware Requirements
- Proxmox VE 8.0+ cluster (minimum 4 nodes recommended)
- Per node: 8+ CPU cores, 32GB+ RAM, 500GB+ storage
- Ceph or similar distributed storage configured
- Network bridge configured (vmbr1)

### Software Requirements
```bash
# Install required tools
sudo apt update
sudo apt install -y python3 python3-pip ansible packer terraform kubectl

# Python dependencies
pip3 install -r requirements.txt

# Install OpenTofu (optional, replaces Terraform)
curl -sSL https://get.opentofu.org/install.sh | bash
```

### Proxmox Configuration
1. API token created with appropriate permissions
2. Storage pool named 'rbd' (or update configuration)
3. Network bridge 'vmbr1' configured
4. DNS configured and working

## Deployment Phases

### Phase 1: Environment Validation
Validates all prerequisites are met:
```bash
cd scripts
python3 01-validate-environment.py
```

### Phase 2: Build Golden Image
Creates Kubernetes-ready VM template with Packer:
```bash
./02-build-golden-image.sh
```

### Phase 3: Provision Infrastructure
Deploys VMs using OpenTofu/Terraform:
```bash
./03-provision-infrastructure.sh
```

### Phase 4: Bootstrap Kubernetes
Initializes cluster with kubeadm via Ansible:
```bash
./04-bootstrap-kubernetes.sh
```

### Phase 5: Deploy Platform Services
Installs essential services (CNI, CSI, monitoring, etc.):
```bash
./05-deploy-platform-services.sh
```

## Main Orchestrator

The `deploy-cluster.py` script orchestrates all phases:

```bash
# Full deployment
python3 deploy-cluster.py deploy

# Skip specific phases
python3 deploy-cluster.py deploy --skip-phases VALIDATE BUILD_IMAGE

# Force rebuild (ignore completed phases)
python3 deploy-cluster.py deploy --force-rebuild

# Check deployment status
python3 deploy-cluster.py status

# Clean up all resources
python3 deploy-cluster.py cleanup

# Reset deployment state
python3 deploy-cluster.py reset
```

## Configuration

### Cluster Settings
Edit configuration at the top of each phase script:

```bash
# scripts/03-provision-infrastructure.sh
CONTROL_NODES=3
WORKER_NODES=4

# scripts/04-bootstrap-kubernetes.sh
KUBE_VERSION="1.30.0"
POD_NETWORK="10.244.0.0/16"
SERVICE_NETWORK="10.96.0.0/12"
```

### Proxmox Settings
Update Proxmox connection details:

```bash
# terraform/main.tf
variable "proxmox_host" {
  default = "10.10.1.21"
}

variable "proxmox_token" {
  default = "packer@pam!packer=<your-token>"
}
```

## Cluster Architecture

### Default Configuration
- **Control Plane**: 3 nodes (HA with keepalived/haproxy)
- **Worker Nodes**: 4 nodes
- **CNI**: Cilium (production-ready, eBPF-based)
- **CSI**: Proxmox CSI (integrates with Ceph)
- **Load Balancer**: MetalLB (bare-metal LoadBalancer)
- **Ingress**: NGINX Ingress Controller
- **Monitoring**: Prometheus + Grafana stack
- **Backup**: Velero with S3 backend
- **Dashboard**: Kubernetes Dashboard
- **Certificates**: cert-manager

### Network Layout
```
10.10.1.99    - Control plane VIP (keepalived)
10.10.1.100-102 - Control plane nodes
10.10.1.110-113 - Worker nodes
10.10.1.150-180 - MetalLB IP pool
```

## Accessing the Cluster

### kubectl Access
```bash
export KUBECONFIG=~/.kube/config-k8s-cluster
kubectl get nodes
kubectl get pods -A
```

### Dashboard Access
```bash
# Get token
cat manifests/monitoring/dashboard-token.txt

# Start proxy
kubectl proxy

# Access at: http://localhost:8001/api/v1/namespaces/kubernetes-dashboard/services/https:kubernetes-dashboard:/proxy/
```

### Grafana Access
```bash
kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80
# Access at: http://localhost:3000
# Username: admin, Password: admin
```

### Prometheus Access
```bash
kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090
# Access at: http://localhost:9090
```

## Troubleshooting

### Check Phase Logs
Each phase creates detailed logs:
```bash
# Check deployment state
cat scripts/deployment-state.json

# Check Terraform state
cd terraform && terraform show

# Check Ansible logs
ansible -i ansible/inventory.yml all -m ping
```

### Common Issues

**VMs won't start:**
- Check Proxmox storage space
- Verify template ID 9000 exists
- Check resource availability

**Kubernetes won't initialize:**
- Verify network connectivity between nodes
- Check swap is disabled
- Ensure containerd is running

**Services won't deploy:**
- Check cluster DNS (CoreDNS pods)
- Verify storage class is available
- Check resource quotas

### Reset and Retry
```bash
# Clean up everything
python3 deploy-cluster.py cleanup

# Reset state
python3 deploy-cluster.py reset

# Start fresh
python3 deploy-cluster.py deploy
```

## Production Considerations

### High Availability
- Control plane uses 3 nodes with stacked etcd
- HAProxy + Keepalived for API server HA
- Applications should use multiple replicas
- Configure pod disruption budgets

### Security
- Enable RBAC (default)
- Use network policies (Cilium)
- Implement pod security policies
- Regular security updates
- Secrets management (consider Sealed Secrets or Vault)

### Backup Strategy
- Velero configured for cluster backup
- Regular etcd snapshots
- Persistent volume backups
- Application-level backups

### Monitoring
- Prometheus metrics collection
- Grafana dashboards
- Alert rules configuration
- Log aggregation (consider adding Loki)

### Scaling
- Add worker nodes by updating `WORKER_NODES` and re-running Phase 3
- Horizontal Pod Autoscaler for applications
- Cluster Autoscaler integration possible
- Vertical Pod Autoscaler for right-sizing

## Directory Structure
```
kubernetes-cluster/
├── README.md                 # This file
├── ARCHITECTURE.md          # Detailed architecture decisions
├── requirements.txt         # Python dependencies
│
├── scripts/                 # Phase-based deployment scripts
│   ├── 01-validate-environment.py
│   ├── 02-build-golden-image.sh
│   ├── 03-provision-infrastructure.sh
│   ├── 04-bootstrap-kubernetes.sh
│   ├── 05-deploy-platform-services.sh
│   └── deploy-cluster.py    # Main orchestrator
│
├── packer/                  # Packer templates
│   ├── ubuntu-k8s-golden.pkr.hcl
│   └── http/               # Cloud-init configs
│
├── terraform/              # Infrastructure as Code
│   ├── main.tf
│   ├── variables.tf
│   └── templates/
│
├── ansible/                # Configuration management
│   ├── inventory.yml
│   ├── bootstrap-k8s.yml
│   └── roles/
│
└── manifests/             # Kubernetes manifests
    ├── networking/
    ├── storage/
    └── monitoring/
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

MIT License - See LICENSE file for details

## Support

For issues, questions, or contributions:
- Open an issue on GitHub
- Check existing documentation
- Review [ARCHITECTURE.md](ARCHITECTURE.md) for design details

## Acknowledgments

Built with industry-standard tools:
- [Proxmox VE](https://www.proxmox.com/)
- [Kubernetes](https://kubernetes.io/)
- [Packer](https://www.packer.io/)
- [OpenTofu](https://opentofu.org/)
- [Ansible](https://www.ansible.com/)
- [Cilium](https://cilium.io/)

---

**Status**: Production Ready | **Version**: 2.0 | **Last Updated**: 2024