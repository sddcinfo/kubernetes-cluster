# Script Execution Order and Structure

## Overview
This document outlines the proper execution order and structure of all automation scripts for the Kubernetes cluster deployment, ensuring efficiency and reliability for both new and existing cluster scenarios.

## Phase-Based Execution Model

### Phase 1-2: Foundation Setup and Template Creation
**Scripts**: 
- `scripts/cluster-manager.py` - Consolidated foundation setup and template management
- `scripts/cluster-deploy.py` - Main deployment orchestrator

#### Execution Order with cluster-manager.py:
1. **Foundation Setup** (`--setup-foundation`)
   - Environment validation with re-run optimization
   - Packer user setup with ACL permissions and token management
   - RBD-ISO storage configuration
   - Cloud image preparation with qemu-guest-agent verification
   - State tracking to enable safe re-runs

2. **Template Creation** (`--create-templates`)
   - Creates base template (VM ID: 9000) - Ubuntu 24.04 with cloud-init
   - Creates Kubernetes template (VM ID: 9001) - Pre-installed K8s v1.33.4 components
   - Full validation of prerequisites before template creation
   - Automatic IP detection via qemu-guest-agent

#### State Management Features:
- **Persistent State**: Tracks completed phases in `~/.kube-cluster/cluster-manager-state.json`
- **Smart Re-runs**: Skips completed phases automatically
- **Drift Detection**: Validates actual resource state, not just existence
- **Force Rebuild**: `--force-rebuild` flag for complete reset

#### Usage Examples:
```bash
# First run on new cluster - foundation setup
python3 scripts/cluster-manager.py --setup-foundation

# Create templates from cloud images
python3 scripts/cluster-manager.py --create-templates

# Combined setup and template creation
python3 scripts/cluster-manager.py --setup-and-create

# Check current status
python3 scripts/cluster-manager.py --status

# Force specific phases to re-run
python3 scripts/cluster-manager.py --setup-foundation --skip-phases cloud_image

# Force complete rebuild (destructive)
python3 scripts/cluster-manager.py --create-templates --force-rebuild
```

### Phase 2.5: DNS Configuration
**Script**: `scripts/deploy-dns-config.py`
**Purpose**: Deploy Kubernetes DNS configuration with desired state approach

#### Features:
- **Desired State**: Always overwrites from source control
- **No Backups**: Prevents duplicate DNS records
- **Validation**: Tests DNS resolution after deployment
- **Idempotent**: Safe to run multiple times

#### Usage:
```bash
python3 scripts/deploy-dns-config.py
```

### Phase 3: VM Provisioning
**Script**: `scripts/provision-control-node.py` (example)
**Purpose**: Provision VMs from templates

#### Example Provisioning:
```bash
# Provision control plane node
python3 scripts/provision-control-node.py
# Creates VM 131 (k8s-control-1) at 10.10.1.31
```

### Phase 4: Infrastructure Orchestration
**Script**: `scripts/cluster-deploy.py`
**Purpose**: Orchestrate complete cluster deployment

#### Deployment Profiles:
- **single-node**: All-in-one Kubernetes node for development
- **single-master**: 1 control plane + 2 workers
- **ha-cluster**: 3 control planes + 4 workers (production)

#### Commands:
```bash
# Deploy single node cluster
python3 cluster-deploy.py deploy --profile single-node

# Deploy HA cluster
python3 cluster-deploy.py deploy --profile ha-cluster

# Deploy specific components
python3 cluster-deploy.py deploy --components foundation template-manager infrastructure

# Check deployment status
python3 cluster-deploy.py status

# Clean up all resources
python3 cluster-deploy.py cleanup
```

### Phase 5: Kubernetes Bootstrap
**Script**: `scripts/04-bootstrap-kubernetes.sh`
**Purpose**: Initialize Kubernetes cluster with kubeadm

#### Features:
- Control plane initialization
- Worker node joining
- CNI (Cilium) deployment
- Initial cluster configuration

### Phase 6: Platform Services
**Script**: `scripts/05-deploy-platform-services.sh`
**Purpose**: Deploy essential platform services

#### Services:
- Ingress controller (NGINX)
- Monitoring (Prometheus/Grafana)
- Certificate management (cert-manager)
- Storage (Proxmox CSI)
- Backup (Velero)

## Complete Deployment Workflow

### New Cluster Deployment
```bash
# Phase 1-2: Foundation setup and template creation (10-15 minutes)
python3 scripts/cluster-manager.py --setup-and-create

# Deploy DNS configuration
python3 scripts/deploy-dns-config.py

# Phase 3-6: Deploy complete cluster with orchestrator
python3 scripts/cluster-deploy.py deploy --profile ha-cluster

# Or manually provision and bootstrap:
# Provision VMs from templates
python3 scripts/provision-control-node.py  # Repeat for each node

# Bootstrap Kubernetes
./scripts/04-bootstrap-kubernetes.sh

# Deploy platform services
./scripts/05-deploy-platform-services.sh
```

### Existing Cluster Updates
```bash
# Verify foundation and templates (fast if no changes)
python3 scripts/cluster-manager.py --status

# Update DNS if needed
python3 scripts/deploy-dns-config.py

# Scale or update cluster
python3 scripts/cluster-deploy.py deploy --components infrastructure

# Add new services
./scripts/05-deploy-platform-services.sh
```

## Script Reliability Features

### Idempotency
All scripts are designed to be idempotent:
- cluster-manager.py uses comprehensive state tracking
- Templates verified before creation
- DNS deployment uses desired state
- Kubernetes scripts check existing resources

### Error Handling
- **Timeouts**: All long-running operations have explicit timeouts
- **Retries**: Network operations include retry logic
- **Validation**: Each phase validates success before proceeding
- **Script Encoding**: Base64 encoding prevents shell interpretation issues

### Performance Optimizations
- **State Caching**: Completed phases tracked and skipped
- **Template Reuse**: Cloud images cached locally
- **Smart Detection**: Only necessary work is performed
- **Fast Re-runs**: Validation completes quickly when resources exist

## Troubleshooting

### Common Issues and Solutions

#### qemu-guest-agent Issues
```bash
# Force cloud image recreation with proper agent installation
rm -f /mnt/rbd-iso/template/images/ubuntu-24.04-cloudimg-amd64-modified.img
python3 scripts/cluster-manager.py --setup-foundation --skip-phases dns_config rbd_storage
```

#### Template Creation Failures
```bash
# Force rebuild of templates
python3 scripts/cluster-manager.py --create-templates --force-rebuild
```

#### State Corruption
```bash
# Reset state and start fresh
rm ~/.kube-cluster/cluster-manager-state.json
python3 scripts/cluster-manager.py --setup-and-create
```

#### DNS Issues
```bash
# Force DNS deployment
python3 scripts/deploy-dns-config.py --force
```

## Best Practices

1. **Always verify templates first** - Use `cluster-manager.py --status` to check state
2. **Use consolidated scripts** - cluster-manager.py handles both foundation and templates
3. **Monitor qemu-guest-agent** - Ensures proper IP detection for VMs
4. **Check logs for errors** - Scripts provide detailed colored output
5. **Backup before destructive operations** - Especially before `--force-rebuild`

## Script Dependencies

```
cluster-manager.py --setup-foundation
    ↓
cluster-manager.py --create-templates
    ↓
deploy-dns-config.py
    ↓
cluster-deploy.py (or manual provisioning)
    ↓
04-bootstrap-kubernetes.sh
    ↓
05-deploy-platform-services.sh
```

Each script depends on the successful completion of the previous phase.

## Key Improvements in Current Implementation

1. **Consolidated Scripts**: Reduced from 3 scripts to 2 (cluster-manager.py replaces cluster-foundation-setup.py and template-manager.py)
2. **Cloud Image Based**: Direct use of Ubuntu cloud images instead of Packer for simpler workflow
3. **qemu-guest-agent**: Properly installed and verified for reliable IP detection
4. **Base64 Encoding**: Script transfer uses base64 to prevent shell interpretation issues
5. **Template Validation**: Both base (9000) and Kubernetes (9001) templates properly validated
6. **Kubernetes v1.33.4**: Updated to latest stable version with all components pre-installed