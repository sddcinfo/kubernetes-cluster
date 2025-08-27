# IP Address Allocation Strategy

## Network Overview
- **Network**: 10.10.1.0/24
- **Gateway**: 10.10.1.1
- **Domain**: sddc.info

## Current Allocations (Base Infrastructure)

### Infrastructure Services (10.10.1.1-10)
- `10.10.1.1` - gateway.sddc.info (dnsmasq/DHCP server)
- `10.10.1.2` - switch1g.sddc.info
- `10.10.1.3` - switch10gb.sddc.info
- `10.10.1.4-10` - Reserved for future infrastructure

### Management Consoles (10.10.1.11-20)
- `10.10.1.11` - console-node1
- `10.10.1.12` - console-node2
- `10.10.1.13` - console-node3
- `10.10.1.14` - console-node4
- `10.10.1.15-20` - Reserved for additional consoles

### Physical Nodes (10.10.1.21-29)
- `10.10.1.21` - node1 (Proxmox)
- `10.10.1.22` - node2 (Proxmox)
- `10.10.1.23` - node3 (Proxmox)
- `10.10.1.24` - node4 (Proxmox)
- `10.10.1.25-29` - Reserved for additional physical nodes

## Kubernetes Cluster Allocations (10.10.1.30-99)

### Control Plane (10.10.1.30-39)
- `10.10.1.30` - k8s-vip (Virtual IP for HA control plane)
- `10.10.1.31` - k8s-control-1
- `10.10.1.32` - k8s-control-2
- `10.10.1.33` - k8s-control-3
- `10.10.1.34-39` - Reserved for additional control nodes

### Worker Nodes (10.10.1.40-49)
- `10.10.1.40` - k8s-worker-1
- `10.10.1.41` - k8s-worker-2
- `10.10.1.42` - k8s-worker-3
- `10.10.1.43` - k8s-worker-4
- `10.10.1.44-49` - Reserved for scaling (6 additional workers)

### MetalLB LoadBalancer Pool (10.10.1.50-79)
- `10.10.1.50-79` - 30 IPs for Kubernetes LoadBalancer services
  - Ingress controllers
  - External services
  - Application load balancers

### Kubernetes Infrastructure Services (10.10.1.80-89)
- `10.10.1.80` - Reserved for monitoring stack VIP
- `10.10.1.81` - Reserved for logging stack VIP
- `10.10.1.82` - Reserved for registry
- `10.10.1.83-89` - Reserved for future infrastructure services

### Future Expansion (10.10.1.90-99)
- `10.10.1.90-99` - Reserved for future use

## Dynamic DHCP Range (10.10.1.100-200)
- `10.10.1.100-200` - DHCP pool for dynamic clients
  - Temporary VMs
  - PXE boot clients
  - Unknown devices

## High Address Space (10.10.1.201-254)

### Development/Test Clusters (10.10.1.201-230)
- `10.10.1.201-210` - Dev cluster control plane
- `10.10.1.211-220` - Dev cluster workers
- `10.10.1.221-230` - Dev cluster services

### Reserved (10.10.1.231-254)
- `10.10.1.231-254` - Reserved for future use

## DNS Naming Convention

### Base Infrastructure
- Physical hosts: `node{N}.sddc.info`
- Console servers: `console-node{N}.sddc.info`
- Network equipment: `{device}{speed}.sddc.info`

### Kubernetes Clusters
- Control plane: `k8s-control-{N}.sddc.info`
- Workers: `k8s-worker-{N}.sddc.info`
- VIPs: `k8s-vip.sddc.info`
- Services: `{service}-k8s.sddc.info`

### Development/Test
- Format: `{env}-k8s-{type}-{N}.sddc.info`
- Example: `dev-k8s-control-1.sddc.info`

## Implementation Guidelines

1. **Static Reservations**: All infrastructure should use DHCP reservations or static IPs
2. **DNS Records**: Every static IP should have both A and PTR records
3. **Documentation**: Update this document when allocating new ranges
4. **Monitoring**: Configure monitoring for IP conflicts and exhaustion
5. **Segmentation**: Consider VLANs for production vs development separation

## Migration from Previous Allocation

If you have existing Kubernetes deployments using the old allocation (100-102, 110-113), migrate using:

1. Deploy new cluster with new IPs (30-49)
2. Migrate workloads
3. Decommission old cluster
4. Update DNS records

## Configuration Files

- **Base Infrastructure**: `/etc/dnsmasq.d/provisioning.conf`
- **Kubernetes Cluster**: `/etc/dnsmasq.d/kubernetes.conf`
- **Development Clusters**: `/etc/dnsmasq.d/development.conf`

Each configuration file should be self-contained and not conflict with others.