# Complete Rebuild Impact Analysis

## What Will Be Created/Modified

### Proxmox Changes
- API tokens for packer@pam and terraform@pam users
- New roles: PackerRole, TerraformRole  
- VM templates: 9001 (base), 9003 (golden image)
- VMs: 101-103 (control plane), 111-114 (workers)

### Files Created
- packer-token.txt (sensitive)
- terraform-token.txt (sensitive)
- Various log files

### Network Impact
- Static IP allocations: 10.10.1.30-36
- No changes to DHCP range (10.10.1.100-200)

## Recovery Procedure
If rebuild fails:
1. Delete created VMs: `qm destroy 101 102 103 111 112 113 114`
2. Delete templates: `qm destroy 9001 9003`
3. Remove API tokens via Proxmox web UI
4. Remove users: `pveum user delete packer@pam terraform@pam`
5. Remove roles: `pveum role delete PackerRole TerraformRole`

## Testing Strategy
- Validate-only mode available: `./complete-rebuild-automation.py --validate-only`
- Phase-by-phase execution with resume capability
- Comprehensive logging for troubleshooting
