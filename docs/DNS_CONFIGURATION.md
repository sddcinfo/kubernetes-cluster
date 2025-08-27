# DNS and Network Configuration

## Overview
This document describes the modular DNS configuration approach implemented for the Kubernetes cluster deployment, designed to coexist with existing infrastructure DNS without conflicts.

## Problem Solved
- **IP Conflicts**: Original Kubernetes IP allocation conflicted with DHCP range (10.10.1.100-200)
- **Monolithic Config**: Single DNS configuration file was difficult to maintain for multiple projects
- **DNS Management**: No systematic approach to DNS record management for Kubernetes services

## Solution Implemented

### 1. Modular DNS Configuration
- **Base Infrastructure**: `/etc/dnsmasq.d/provisioning.conf` (existing)
- **Kubernetes Cluster**: `/etc/dnsmasq.d/kubernetes.conf` (new)
- **Future Projects**: Can add additional `.conf` files as needed

### 2. Strategic IP Allocation
- **Base Infrastructure**: 10.10.1.1-29 (existing)
- **Kubernetes Control**: 10.10.1.30-39 (VIP + 3 control nodes)
- **Kubernetes Workers**: 10.10.1.40-49 (4 workers + expansion room)
- **MetalLB LoadBalancer**: 10.10.1.50-79 (30 IPs for services)
- **K8s Infrastructure**: 10.10.1.80-89 (monitoring, logging, etc.)
- **Future Expansion**: 10.10.1.90-99
- **DHCP Range**: 10.10.1.100-200 (unchanged)
- **Development**: 10.10.1.201+ (for test clusters)

## Implementation Details

### DNS Records Created
```
# Control Plane
k8s-vip.sddc.info          -> 10.10.1.30
k8s-control-1.sddc.info    -> 10.10.1.31
k8s-control-2.sddc.info    -> 10.10.1.32
k8s-control-3.sddc.info    -> 10.10.1.33

# Workers
k8s-worker-1.sddc.info     -> 10.10.1.40
k8s-worker-2.sddc.info     -> 10.10.1.41
k8s-worker-3.sddc.info     -> 10.10.1.42
k8s-worker-4.sddc.info     -> 10.10.1.43

# Services
ingress.k8s.sddc.info      -> 10.10.1.50
prometheus.k8s.sddc.info   -> 10.10.1.51
grafana.k8s.sddc.info      -> 10.10.1.52
registry.k8s.sddc.info     -> 10.10.1.53

# Aliases
k8s-api.sddc.info          -> k8s-vip.sddc.info
kubernetes.sddc.info       -> k8s-vip.sddc.info
dashboard.k8s.sddc.info    -> ingress.k8s.sddc.info
```

### Wildcard DNS
- `*.apps.sddc.info` resolves to `10.10.1.50` (ingress controller)

## Updated Configurations

### Terraform/OpenTofu
- Control plane VMs: 131-133 (IPs: 10.10.1.31-33)
- Worker VMs: 140-143 (IPs: 10.10.1.40-43)
- Updated golden template reference to VM 9001
- Fixed SSH key paths and username (sysadmin)

### Kubernetes Bootstrap
- Control plane VIP updated to `10.10.1.30`

### Platform Services
- MetalLB address pool: `10.10.1.50-10.10.1.79`

## Deployment Process

### 1. Deploy DNS Configuration
```bash
python3 scripts/deploy-dns-config.py
```

### 2. Verify DNS Resolution
```bash
# Test key records
nslookup k8s-vip.sddc.info 10.10.1.1
nslookup k8s-control-1.sddc.info 10.10.1.1
nslookup k8s-worker-1.sddc.info 10.10.1.1

# Test reverse DNS
nslookup 10.10.1.30 10.10.1.1
```

### 3. Deploy Infrastructure
```bash
# Terraform/OpenTofu will use the new IP allocations
cd terraform
terraform plan
terraform apply
```

## Key Files Modified

### New Files
- `docs/IP_ALLOCATION.md` - Complete IP allocation strategy
- `configs/dnsmasq.d/kubernetes.conf` - Kubernetes DNS configuration
- `scripts/deploy-dns-config.py` - DNS deployment script (Python)
- `docs/DNS_CONFIGURATION.md` - This documentation

### Updated Files
- `terraform/main.tf` - Updated IP allocations and VM IDs
- `scripts/04-bootstrap-kubernetes.sh` - Updated control VIP
- `scripts/05-deploy-platform-services.sh` - Updated MetalLB range
- `/etc/dnsmasq.conf` - Enabled conf-dir inclusion

## Verification Results

✅ **DNS Resolution Working**
- Forward DNS: All Kubernetes hostnames resolve correctly
- Reverse DNS: PTR records working for all IPs
- Wildcard DNS: *.apps.sddc.info resolves to ingress
- Coexistence: No conflicts with existing infrastructure DNS

✅ **Configuration Validation**
- dnsmasq syntax check: PASSED
- Service restart: SUCCESSFUL  
- No conflicts with DHCP range
- Modular configuration working

## Benefits Achieved

1. **No IP Conflicts**: Kubernetes IPs are outside DHCP range
2. **Modular Management**: Each project has its own DNS config
3. **Scalability**: Room for expansion in each category
4. **Maintainability**: Clear separation of concerns
5. **Documentation**: Complete IP allocation strategy
6. **Automation**: Scripts for deployment and verification

## Future Expansion

To add new projects (e.g., development clusters):

1. Allocate IPs from available ranges
2. Create new `/etc/dnsmasq.d/{project}.conf`
3. Deploy with the deployment script
4. Update documentation

The modular approach ensures no conflicts and easy management.