# Kubernetes Cluster VM Allocation Plan

## Resource Distribution Strategy

### Control Plane Nodes (3 VMs)
| VM Name | vCPUs | Memory | Storage | Target Node | HA Group |
|---------|-------|--------|---------|-------------|----------|
| k8s-control-01 | 4 | 8GB | 64GB | node1 | k8s-control-plane |
| k8s-control-02 | 4 | 8GB | 64GB | node2 | k8s-control-plane |
| k8s-control-03 | 4 | 8GB | 64GB | node3 | k8s-control-plane |

### Worker Nodes (4 VMs)
| VM Name | vCPUs | Memory | Storage | Target Node | HA Group |
|---------|-------|--------|---------|-------------|----------|
| k8s-worker-01 | 6 | 24GB | 128GB | node1 | k8s-workers |
| k8s-worker-02 | 6 | 24GB | 128GB | node2 | k8s-workers |
| k8s-worker-03 | 6 | 24GB | 128GB | node3 | k8s-workers |
| k8s-worker-04 | 6 | 24GB | 128GB | node4 | k8s-workers |

## Resource Utilization Summary
- **Total allocated vCPUs**: 42/48 (87.5% - allows for overhead)
- **Total allocated Memory**: 264GB/502GB (52.6% - excellent buffer for failover)
- **Storage**: All VMs on Ceph RBD for HA and performance

## HA Anti-Affinity Rules
1. **k8s-control-plane group**: `affinity=separate` - ensures no two control plane VMs on same physical node
2. **k8s-workers group**: `affinity=separate` - distributes worker load optimally
3. **Priority**: Control plane VMs = 100, Worker VMs = 50

## Network Configuration
- **Management**: 10.10.1.0/24 (existing)
- **Kubernetes Pod Network**: 10.244.0.0/16 (Calico default)
- **Service Network**: 10.96.0.0/12 (Kubernetes default)
- **MetalLB Pool**: 10.10.1.200-10.10.1.220 (20 LoadBalancer IPs)