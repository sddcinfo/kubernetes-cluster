# Complete Proxmox Kubernetes Rebuild - Automation Checklist

## Critical Manual Steps That Must Be Automated

### 1. Proxmox Initial Setup (Currently Manual - NEEDS AUTOMATION)
- [ ] **API Token Creation with Correct Permissions**
  ```bash
  # These exact commands must be in automation:
  pveum user add packer@pam --password somepassword
  pveum role add PackerRole -privs "VM.Allocate,VM.Clone,VM.Config.CDROM,VM.Config.CPU,VM.Config.Disk,VM.Config.HWType,VM.Config.Memory,VM.Config.Network,VM.Config.Options,VM.Monitor,VM.Audit,VM.PowerMgmt,VM.GuestAgent.Audit,VM.GuestAgent.Unrestricted,Datastore.AllocateSpace,Datastore.Audit,Pool.Allocate"
  pveum aclmod / -user packer@pam -role PackerRole
  pveum user token add packer@pam packer --privsep=0
  # TOKEN: 7b2a3da7-bd30-4772-a6b0-874aa9b2f3a5 (save this!)
  ```

- [ ] **Terraform User Setup** (For production use)
  ```bash
  pveum user add terraform@pam --password strongpassword
  pveum role add TerraformRole -privs "VM.Allocate,VM.Clone,VM.Config.CDROM,VM.Config.CPU,VM.Config.Disk,VM.Config.HWType,VM.Config.Memory,VM.Config.Network,VM.Config.Options,VM.Monitor,VM.Audit,VM.PowerMgmt,Datastore.AllocateSpace,Datastore.Audit,Pool.Allocate"
  pveum aclmod / -user terraform@pam -role TerraformRole
  pveum user token add terraform@pam terraform --privsep=0
  ```

### 2. Base Template Creation (AUTOMATED - but verify these settings)
- [ ] **Ubuntu Cloud Image Upload** ✓ (in k8s_proxmox_deployer.py)
- [ ] **VM 9001 Configuration** ✓ (automated)
  - EFI boot ✓
  - VirtIO disk/network ✓
  - QEMU guest agent ✓
  - Cloud-init ✓
  - SSH key injection ✓
  - Disk resize to 10GB ✓ (CRITICAL: was 3.5GB, caused failures)

### 3. Packer Configuration (PARTIALLY AUTOMATED - needs updates)
- [ ] **Working Packer Config** - Update with latest fixes:
  ```hcl
  # These are the PROVEN working settings that MUST be in automation:
  ssh_timeout          = "20m"   # CRITICAL: was 5m, caused failures
  ssh_handshake_attempts = 50    # Reasonable retry attempts
  ssh_pty              = true    # Enable pseudo-terminal
  task_timeout         = "10m"   # Task execution timeout
  qemu_agent           = true    # CRITICAL for IP detection
  ```
- [ ] **Golden Image Build** - Template 9003 ✓ (created successfully)

### 4. Terraform Configuration (NEEDS MAJOR UPDATE)
Current issues found:
- [ ] **Provider Choice**: Research shows Telmate is more reliable than BPG
- [ ] **Authentication**: Password auth more reliable than API tokens initially
- [ ] **Connectivity Testing**: Must verify API before deployment

### 5. Network and DHCP (VERIFY IN AUTOMATION)
- [ ] **DHCP Range Configuration**: 10.10.1.100-200 ✓
- [ ] **Static IP Reservations**: Control plane .30-.44 range ✓
- [ ] **DNS Configuration**: Verify working

### 6. Kubernetes Deployment (IN AUTOMATION - but untested)
- [ ] **Kubeadm Configuration** ✓
- [ ] **CNI Setup** ✓ 
- [ ] **Storage Classes** ✓

## New Automation Requirements Discovered

### A. Pre-Flight Checks (MISSING - must add)
```bash
#!/bin/bash
# Add to k8s_proxmox_deployer.py
check_proxmox_connectivity() {
    curl -k -H "Authorization: PVEAPIToken=packer@pam!packer:TOKEN" \
         "https://10.10.1.21:8006/api2/json/version" || exit 1
}
```

### B. API Token Validation (MISSING - must add)
- Verify token has correct permissions
- Test all required API endpoints
- Fail fast if permissions insufficient

### C. Template Verification (PARTIALLY IMPLEMENTED)
- Verify template 9001 exists and is properly configured
- Verify template 9003 (golden image) was created successfully
- Check qemu-guest-agent is installed and running

### D. Terraform Provider Selection Logic (NEW REQUIREMENT)
Based on research:
- Try BPG provider first (feature-rich)
- Fall back to Telmate if BPG fails (more reliable)
- Use password auth initially, migrate to tokens

## Files That Need Updates

### 1. k8s_proxmox_deployer.py
- [ ] Add API token creation automation
- [ ] Add pre-flight connectivity checks
- [ ] Update Packer config with proven settings
- [ ] Add Terraform provider fallback logic

### 2. Packer Templates
- [ ] Update ubuntu-golden-simple.pkr.hcl with all fixes
- [ ] Ensure 20-minute SSH timeout
- [ ] Verify qemu-agent installation

### 3. Terraform Configuration
- [ ] Create robust configuration with provider fallback
- [ ] Add comprehensive connectivity testing
- [ ] Implement step-by-step deployment validation

### 4. New Files Needed
- [ ] proxmox-setup.sh - Initial Proxmox configuration
- [ ] pre-flight-checks.sh - API/network validation
- [ ] terraform-provider-test.sh - Test provider connectivity

## Testing Strategy
1. **Clean Proxmox Installation**
2. **Run Full Automation**
3. **Verify Each Phase**
4. **Document Any Missing Steps**

## Success Criteria
- [ ] Complete rebuild from scratch works without manual intervention
- [ ] All learned fixes are captured in code
- [ ] No loss of knowledge from trial-and-error process
- [ ] Robust error handling and recovery
- [ ] Clear documentation of all requirements