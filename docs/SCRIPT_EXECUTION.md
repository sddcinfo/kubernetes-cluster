# Script Execution Order and Structure

## Overview
This document outlines the proper execution order and structure of all automation scripts for the Kubernetes cluster deployment, ensuring efficiency and reliability for both new and existing cluster scenarios.

## Phase-Based Execution Model

### Phase 1-2: Foundation Setup (Combined)
**Script**: `scripts/cluster-foundation-setup.py`
**Purpose**: Intelligent foundation setup with state management and drift detection

#### Execution Order:
1. **Environment Validation** (cached after first run)
   - SSH connectivity check
   - SSH key verification
   - Network configuration validation
   - RBD storage verification

2. **Tools and Storage Setup** (idempotent)
   - Install required tools (virt-customize)
   - Setup RBD-ISO storage on Proxmox

3. **Packer User Configuration** (token always refreshed)
   - Create/update Packer user on Proxmox
   - Generate fresh API token
   - Apply proper ACL permissions

4. **Cloud Image Preparation** (skipped if exists)
   - Download Ubuntu cloud image
   - Modify with virt-customize
   - Upload to Proxmox storage

5. **Base Template Creation** (drift detection enabled)
   - Create VM 9002 from cloud image
   - Convert to template
   - Validate template flag

6. **Packer Configuration** (always refreshes files)
   - Creates/updates `packer/.env` with current token
   - Updates `packer/variables.json`
   - Ensures configuration is always current

#### State Management Features:
- **Persistent State**: Tracks completed phases in `.foundation-state.json`
- **Smart Re-runs**: Completes in ~2 seconds when all phases are done
- **Drift Detection**: Validates actual resource state, not just existence
- **Force Rebuild**: `--force-rebuild` flag for complete reset

#### Usage Examples:
```bash
# First run on new cluster
python3 scripts/cluster-foundation-setup.py

# Re-run on existing cluster (intelligent skipping)
python3 scripts/cluster-foundation-setup.py

# Force specific phases to re-run
python3 scripts/cluster-foundation-setup.py --skip-phases validation tools_storage

# Check current status
python3 scripts/cluster-foundation-setup.py --status

# Force complete rebuild (destructive)
python3 scripts/cluster-foundation-setup.py --force-rebuild
```

### Golden Image Build
**Command**: `packer build -var-file=packer/variables.json packer/ubuntu-golden.pkr.hcl`
**Purpose**: Build golden template from base template

#### Features:
- Uses token from `.env` or `variables.json`
- Creates VM 9001 as golden template
- Installs updates and qemu-guest-agent
- Cleans cloud-init for template use

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

### Phase 3: Infrastructure Provisioning
**Directory**: `terraform/`
**Technology**: OpenTofu/Terraform

#### Commands:
```bash
cd terraform
terraform init        # First time only
terraform plan        # Review changes
terraform apply       # Deploy VMs
```

### Phase 4: Kubernetes Bootstrap
**Script**: `scripts/04-bootstrap-kubernetes.sh`
**Purpose**: Initialize Kubernetes cluster with kubeadm

#### Features:
- Control plane initialization
- Worker node joining
- CNI (Cilium) deployment
- Initial cluster configuration

### Phase 5: Platform Services
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
# Phase 1-2: Foundation setup (10-15 minutes)
python3 scripts/cluster-foundation-setup.py

# Build golden image (5-10 minutes)
packer build -var-file=packer/variables.json packer/ubuntu-golden.pkr.hcl

# Deploy DNS configuration
python3 scripts/deploy-dns-config.py

# Phase 3: Deploy infrastructure
cd terraform && terraform apply

# Phase 4: Bootstrap Kubernetes
cd ../scripts && ./04-bootstrap-kubernetes.sh

# Phase 5: Deploy platform services
./05-deploy-platform-services.sh
```

### Existing Cluster Updates
```bash
# Verify foundation (2 seconds if no changes)
python3 scripts/cluster-foundation-setup.py

# Update DNS if needed
python3 scripts/deploy-dns-config.py

# Scale infrastructure
cd terraform && terraform apply

# Add new services
cd ../scripts && ./05-deploy-platform-services.sh
```

## Script Reliability Features

### Idempotency
All scripts are designed to be idempotent:
- Foundation setup uses state tracking
- DNS deployment uses desired state
- Terraform manages infrastructure state
- Kubernetes scripts check existing resources

### Error Handling
- **Timeouts**: All long-running operations have explicit timeouts
- **Retries**: Network operations include retry logic
- **Validation**: Each phase validates success before proceeding
- **Rollback**: Failed operations don't leave partial state

### Performance Optimizations
- **State Caching**: Completed phases tracked and skipped
- **Parallel Operations**: Where possible, operations run concurrently
- **Smart Detection**: Only necessary work is performed
- **Fast Re-runs**: Full validation takes ~2 seconds when complete

## Troubleshooting

### Common Issues and Solutions

#### Script Timeouts
```bash
# Increase timeout for slow networks
python3 scripts/cluster-foundation-setup.py --timeout 600
```

#### State Corruption
```bash
# Reset state and start fresh
python3 scripts/cluster-foundation-setup.py --reset-state
```

#### Template Drift
```bash
# Force rebuild of templates
python3 scripts/cluster-foundation-setup.py --force-rebuild
```

#### DNS Issues
```bash
# Force DNS deployment
python3 scripts/deploy-dns-config.py --force
```

## Best Practices

1. **Always run foundation setup first** - Even on existing clusters, it validates environment
2. **Check status before major operations** - Use `--status` flag to review state
3. **Use force flags sparingly** - Only when you need to override safety checks
4. **Monitor logs** - All scripts provide detailed colored output
5. **Backup before destructive operations** - Especially before `--force-rebuild`

## Script Dependencies

```
cluster-foundation-setup.py
    ↓
packer build
    ↓
deploy-dns-config.py
    ↓
terraform apply
    ↓
04-bootstrap-kubernetes.sh
    ↓
05-deploy-platform-services.sh
```

Each script depends on the successful completion of the previous phase.