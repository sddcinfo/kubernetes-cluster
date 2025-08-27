# Kubernetes on Proxmox - Architecture & Implementation Approach

## Executive Summary

After extensive research and evaluation, the recommended approach for automating Kubernetes cluster deployment on Proxmox is:

1. **Packer** for VM image creation (best tool for the job)
2. **OpenTofu** for infrastructure provisioning (open-source Terraform fork)
3. **Ansible** for configuration management
4. **Python** orchestration with async/await for overall automation

## Tool Selection Rationale

### VM Template Building: Cloud Images + virt-customize ✅

**Why Cloud Images with virt-customize:**
- Official Ubuntu cloud images as base (maintained and secure)
- virt-customize for image modification (part of libguestfs-tools)
- Direct Proxmox API integration for template creation
- Simpler than Packer for cloud image-based workflows
- qemu-guest-agent pre-installed for better VM management

**Alternatives Considered:**
- Packer: Overkill for cloud image-based templates
- Manual template creation: Too error-prone, not repeatable
- Azure VM Image Builder: Azure-specific
- CloudCaptain: AWS/JVM specific

### Infrastructure as Code: OpenTofu ✅

**Why OpenTofu:**
- Open-source fork of Terraform (Apache 2.0 license)
- 100% Terraform compatible (can use existing providers)
- Linux Foundation project (future CNCF member)
- Avoids HashiCorp's BSL licensing concerns
- Strong community backing

**Alternatives Considered:**
- Terraform: BSL license since Aug 2023
- Pulumi: Requires learning programming SDKs, less Proxmox community support
- Crossplane: Kubernetes-native but requires existing K8s cluster (chicken-egg problem)
- Ansible alone: Not declarative for infrastructure state

### Configuration Management: Ansible ✅

**Why Ansible:**
- Agentless architecture
- Idempotent operations
- Excellent Kubernetes support (kubespray, kubeadm modules)
- Wide community adoption
- Simple YAML syntax

### Container Networking: Cilium ✅

**Why Cilium over Calico:**
- **eBPF Performance**: Runs in kernel space, bypassing iptables for better performance
- **Advanced Security**: Layer 7 network policies (HTTP/gRPC/Kafka protocol-aware)
- **Identity-based Security**: Not just IP-based, supports service mesh without sidecars
- **Observability**: Built-in Hubble for deep network visibility and flow monitoring
- **Modern Features**: LoadBalancer implementation, Ingress capabilities, multi-cluster networking
- **Resource Efficiency**: Lower CPU and memory overhead on virtualized infrastructure

**Calico Comparison:**
- **Calico Advantages**: More mature, simpler troubleshooting, wider adoption
- **Calico Limitations**: iptables-based (higher overhead), limited Layer 7 capabilities
- **Enterprise Context**: Cilium's advanced features justify the learning curve for production deployments

### Orchestration: Python with Async/Await ✅

**Why Python:**
- Excellent Proxmox API libraries (proxmoxer)
- Async/await for parallel operations
- Rich ecosystem for automation
- Error handling and retry logic
- Status tracking and reporting

## Architecture Phases

### Phase 1: Base Infrastructure
- Proxmox cluster validation
- Network configuration (VLANs, bridges)
- Storage setup (Ceph RBD pools)
- DNS/DHCP configuration

### Phase 2: Template Creation
- Ubuntu 24.04 LTS cloud image download
- Cloud image customization with virt-customize:
  - qemu-guest-agent installation
  - EFI boot configuration
  - SSH key injection
  - User creation (sysadmin)
- Template creation via Proxmox API:
  - Base template (9000): Ubuntu with cloud-init
  - Kubernetes template (9001): Pre-installed K8s v1.33.4 components

### Phase 3: Infrastructure Provisioning
- OpenTofu deploys:
  - Control plane VMs (3 nodes)
  - Worker VMs (4+ nodes)
  - Load balancer VM (optional)
  - Network configurations
  - Storage attachments

### Phase 4: Kubernetes Bootstrap
- Ansible playbooks for:
  - kubeadm init on first control plane
  - Control plane join for HA
  - Worker node joins
  - CNI installation (Cilium recommended)
  - CSI installation (Proxmox CSI)

### Phase 5: Platform Services
- MetalLB for LoadBalancer services
- Ingress controller (nginx/traefik)
- Monitoring stack (Prometheus/Grafana)
- Log aggregation (Loki/Fluentbit)
- Backup solution (Velero)

## Key Design Decisions

### 1. Cloud-Init Over Autoinstall
- Eliminates GRUB boot command issues
- Faster provisioning
- Native Proxmox integration
- Consistent across Ubuntu versions

### 2. Separation of Concerns
- Cloud Images + virt-customize: Immutable base templates
- OpenTofu: Infrastructure state
- Ansible: Configuration drift prevention
- Python: Orchestration and error handling

### 3. Idempotency First
- All operations must be safely repeatable
- State tracking at each phase
- Rollback capabilities

### 4. Production Readiness
- High availability at every layer
- Automated backup strategies
- Monitoring and alerting
- Security hardening

## Implementation Approach

### Step 1: Clean Foundation
1. Remove all experimental/duplicate files
2. Establish clear directory structure
3. Single source of truth for documentation (README.md)

### Step 2: Modular Scripts
Consolidated approach with intelligent state tracking:
- `cluster-manager.py` - Foundation setup and template creation
- `cluster-deploy.py` - Main deployment orchestrator
- `deploy-dns-config.py` - DNS configuration
- `04-bootstrap-kubernetes.sh` - Kubernetes initialization
- `05-deploy-platform-services.sh` - Platform services deployment

### Step 3: Orchestration Layer
Main orchestrator script:
- `deploy-kubernetes-cluster.py`
- Calls phase scripts in order
- Tracks state and progress
- Handles errors and retries
- Provides status reporting

## Directory Structure
```
kubernetes-cluster/
├── README.md                 # Main documentation
├── ARCHITECTURE.md          # This file - approach and decisions
├── deploy.py               # Main orchestrator
│
├── scripts/                # Phase-based scripts
│   ├── 01-validate.py
│   ├── 02-build-image.sh
│   ├── 03-provision.sh
│   ├── 04-bootstrap.sh
│   └── 05-services.sh
│
├── templates/              # Template configurations
│   └── (deprecated - templates created via cluster-manager.py)
│
├── terraform/              # OpenTofu/Terraform configs
│   ├── main.tf
│   ├── variables.tf
│   └── outputs.tf
│
├── ansible/                # Ansible playbooks
│   ├── inventory.yml
│   ├── site.yml
│   └── roles/
│
└── manifests/             # Kubernetes manifests
    ├── networking/
    ├── storage/
    └── monitoring/
```

## Success Criteria

1. **Reliability**: 95%+ success rate on clean deploys
2. **Speed**: Full cluster deployment < 30 minutes
3. **Idempotency**: Safe to run multiple times
4. **Scalability**: Easy to add/remove nodes
5. **Maintainability**: Clear logs and error messages
6. **Documentation**: Self-documenting code and processes

## Next Steps

1. Clean up existing repository
2. Implement phase-based scripts
3. Test each phase independently
4. Integration testing
5. Documentation update
6. Production deployment

## Technology Stack Summary

| Component | Tool | Version | License |
|-----------|------|---------|---------|
| VM Templates | Cloud Images + virt-customize | Latest | Various |
| Infrastructure | OpenTofu | 1.6+ | Apache 2.0 |
| Configuration | Ansible | 2.16+ | GPL 3.0 |
| Orchestration | Python | 3.11+ | PSF |
| Container Runtime | containerd | 1.7+ | Apache 2.0 |
| Kubernetes | kubeadm | 1.33.4 | Apache 2.0 |
| CNI | Cilium | 1.15+ | Apache 2.0 |
| CSI | Proxmox CSI | Latest | Apache 2.0 |
| Load Balancer | MetalLB | 0.14+ | Apache 2.0 |

This architecture provides a solid, production-ready foundation for Kubernetes on Proxmox that is:
- **Automatable**: Full CI/CD integration possible
- **Repeatable**: Consistent results every time
- **Reliable**: Built on proven tools and patterns
- **Scalable**: Easy to extend and modify