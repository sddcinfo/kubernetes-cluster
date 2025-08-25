# Production-Grade Kubernetes on Proxmox VE 9

This repository contains a complete Infrastructure as Code (IaC) solution for deploying a production-grade Kubernetes cluster on Proxmox VE 9 with high availability, monitoring, logging, and backup capabilities.

## Architecture Overview

### Infrastructure
- **Proxmox Cluster**: 4 nodes with 48 vCPUs total, 502GB RAM, 7.3TB Ceph storage
- **Kubernetes Cluster**: 3 control plane + 4 worker nodes
- **High Availability**: Multi-layered HA with Proxmox HA + Kubernetes HA
- **Storage**: Ceph RBD integration via Proxmox CSI plugin
- **Networking**: MetalLB for LoadBalancer services

### VM Resource Allocation
| Node Type | Count | vCPUs | Memory | Storage | HA Group |
|-----------|-------|-------|--------|---------|----------|
| Control Plane | 3 | 4 | 8GB | 64GB | k8s-control-plane |
| Workers | 4 | 6 | 24GB | 128GB | k8s-workers |

**Total Allocation**: 42 vCPUs (87.5%), 264GB RAM (52.6%) - excellent buffer for failover scenarios.

## Features

### Core Infrastructure
- **Immutable Infrastructure**: Packer-built golden images
- **Declarative Provisioning**: Terraform for VM lifecycle management  
- **Configuration Management**: Ansible for cluster bootstrapping
- **High Availability**: Control plane VIP with keepalived, anti-affinity rules

### Kubernetes Ecosystem
- **CNI**: Calico for pod networking
- **Storage**: Proxmox CSI plugin with dynamic provisioning
- **Load Balancing**: MetalLB for bare-metal LoadBalancer services
- **Infrastructure Awareness**: Proxmox Cloud Controller Manager

### Day 2 Operations
- **Monitoring**: Prometheus + Grafana stack with Proxmox metrics
- **Logging**: Loki + Promtail for centralized log aggregation
- **Backup**: Velero for Kubernetes-native backup and disaster recovery
- **Storage**: MinIO for S3-compatible backup storage

## Quick Start

### Prerequisites
- Proxmox VE 9 cluster (minimum 3 nodes)
- Ceph storage cluster configured
- API tokens for automation
- Ubuntu 24.04 LTS ISO in Proxmox storage

### Installation Tools
```bash
# Install required tools
sudo apt update && sudo apt install -y wget unzip

# Install Packer
wget https://releases.hashicorp.com/packer/1.10.0/packer_1.10.0_linux_amd64.zip
unzip packer_1.10.0_linux_amd64.zip && sudo mv packer /usr/local/bin/

# Install Terraform  
wget https://releases.hashicorp.com/terraform/1.7.0/terraform_1.7.0_linux_amd64.zip
unzip terraform_1.7.0_linux_amd64.zip && sudo mv terraform /usr/local/bin/

# Install Ansible
sudo apt install -y ansible python3-kubernetes
```

### Deploy Cluster
```bash
# Clone and enter directory
git clone <repository-url>
cd kubernetes-cluster

# Configure credentials
cp packer/variables.json.example packer/variables.json
cp terraform/terraform.tfvars.example terraform/terraform.tfvars

# Edit configuration files with your Proxmox details
vim packer/variables.json
vim terraform/terraform.tfvars

# Deploy everything
./deploy.sh all
```

## Manual Deployment Steps

### 1. Build VM Template
```bash
cd packer
packer build -var-file="variables.json" ubuntu-24.04-k8s.pkr.hcl
```

### 2. Provision Infrastructure  
```bash
cd terraform
terraform init
terraform plan
terraform apply
```

### 3. Bootstrap Kubernetes
```bash
cd ansible
ansible-playbook -i inventory/terraform-inventory.ini playbook.yml
```

### 4. Deploy Ecosystem Components
```bash
# Monitoring stack
kubectl apply -f monitoring/

# Backup solution
kubectl create namespace backup
kubectl apply -f backup/
```

## Network Configuration

### IP Allocation
- **Management Network**: 10.10.1.0/24 (existing)
- **Control Plane VIP**: 10.10.1.100
- **Control Plane Nodes**: 10.10.1.101-103  
- **Worker Nodes**: 10.10.1.111-114
- **MetalLB Pool**: 10.10.1.200-220 (LoadBalancer services)

### Kubernetes Networks
- **Pod Network**: 10.244.0.0/16 (Calico)
- **Service Network**: 10.96.0.0/12 (default)

## High Availability Strategy

### Layer 1: Proxmox HA
- Anti-affinity rules prevent control plane co-location
- Automatic VM recovery on node failure
- Priority-based recovery (control plane first)

### Layer 2: Kubernetes HA  
- 3-node etcd cluster with quorum
- keepalived VIP for API server endpoint
- Pod rescheduling on node failure

## Storage Integration

### Proxmox CSI Plugin
- Dynamic volume provisioning from Ceph RBD
- Topology-aware scheduling
- Volume expansion and snapshots

### Default StorageClass
```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: proxmox-rbd
  annotations:
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: csi.proxmox.sinextra.dev
parameters:
  storage: rbd
  csi.storage.k8s.io/fstype: ext4
allowVolumeExpansion: true
```

## Monitoring & Observability

### Metrics Collection
- **Prometheus**: Kubernetes cluster and workload metrics
- **Proxmox Exporter**: Hypervisor and Ceph metrics  
- **Node Exporter**: Host-level metrics
- **Grafana**: Unified dashboards and visualization

### Log Aggregation
- **Loki**: Scalable log aggregation
- **Promtail**: Log collection agent
- **Grafana**: Log query and visualization

### Access Monitoring
```bash
# Get Grafana LoadBalancer IP
kubectl get svc -n monitoring prometheus-stack-grafana

# Default credentials: admin / kubernetes-admin
```

## Backup & Disaster Recovery

### Velero Configuration
- **Application Backup**: Kubernetes resources and PVCs
- **Scheduled Backups**: Daily at 2 AM, 30-day retention
- **CSI Snapshots**: Native volume snapshots
- **S3 Storage**: MinIO for backup storage

### Backup Operations
```bash
# Manual backup
velero backup create manual-backup --include-namespaces default

# List backups  
velero backup get

# Restore from backup
velero restore create --from-backup manual-backup
```

## Security Considerations

### VM Isolation
- KVM virtualization provides hardware-enforced isolation
- Dedicated kernel per VM prevents container escapes
- Network segmentation with VLANs

### Kubernetes Security
- RBAC enabled by default
- Network policies with Calico
- Pod Security Standards enforcement
- Secrets management with external secret operators

## Operational Procedures

### Scaling Operations
```bash
# Scale worker nodes (update Terraform)
vim terraform/main.tf  # Add worker node
terraform apply

# Scale application replicas
kubectl scale deployment app --replicas=5
```

### Maintenance Windows
```bash
# Drain node for maintenance
kubectl drain k8s-worker-01 --ignore-daemonsets --delete-emptydir-data

# Cordon node to prevent new pods
kubectl cordon k8s-worker-01

# Uncordon after maintenance
kubectl uncordon k8s-worker-01
```

### Troubleshooting
```bash
# Check cluster status
kubectl get nodes
kubectl get pods --all-namespaces

# Check Proxmox HA status
pvesh get /cluster/ha/status

# Check Ceph status  
ceph -s

# Check keepalived status
systemctl status keepalived
```

## Performance Optimization

### Ceph Tuning
- NVMe-optimized settings
- Proper PG distribution  
- Network separation (public/cluster)

### Kubernetes Optimization
- Resource requests/limits
- Node affinity rules
- HPA/VPA for auto-scaling

### Network Performance
- VLAN segmentation
- jumbo frames (if supported)
- Multi-path networking

## Disaster Recovery Procedures

### Full Cluster Recovery
1. **Infrastructure Recovery**: Restore Proxmox VMs from Proxmox Backup Server
2. **Application Recovery**: Restore from Velero backups
3. **Data Recovery**: Restore PVCs from CSI snapshots
4. **Validation**: Run cluster validation tests

### Control Plane Recovery
1. **Single Node**: Automatic failover via keepalived
2. **Majority Loss**: Bootstrap new cluster from backup
3. **Complete Loss**: Full cluster restoration procedure

## Contributing

This implementation follows Infrastructure as Code principles and GitOps workflows. All changes should be:

1. Version controlled in Git
2. Tested in staging environment  
3. Applied via automation pipelines
4. Documented and reviewed

## Support

For issues and questions:
- Check troubleshooting guides
- Review monitoring dashboards
- Examine log aggregation
- Validate backup integrity

---

This Kubernetes-on-Proxmox solution provides enterprise-grade reliability, scalability, and operational excellence for production workloads while maintaining the flexibility and cost-effectiveness of open-source technologies.