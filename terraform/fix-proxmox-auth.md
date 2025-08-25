# Proxmox Authentication Fix Guide

## Issue Identified
The API token is not working properly, causing Terraform operations to fail.

## Solution Options (in order of preference)

### Option 1: Fix API Token (Recommended for Production)

1. **Log into Proxmox Web UI as root**

2. **Check existing packer token:**
   - Go to Datacenter > Permissions > API Tokens
   - Find: packer@pam!packer
   - Click Edit and ensure "Privilege Separation" is UNCHECKED

3. **If token doesn't exist, create new one:**
   ```bash
   # SSH to Proxmox node as root
   pveum user add terraform@pve --password strongpassword
   pveum role add TerraformRole -privs "VM.Allocate,VM.Clone,VM.Config.CDROM,VM.Config.CPU,VM.Config.Disk,VM.Config.HWType,VM.Config.Memory,VM.Config.Network,VM.Config.Options,VM.Monitor,VM.Audit,VM.PowerMgmt,Datastore.AllocateSpace,Datastore.Audit,Pool.Allocate"
   pveum aclmod / -user terraform@pve -role TerraformRole
   pveum user token add terraform@pve terraform --privsep=0
   ```

4. **Test new token:**
   ```bash
   curl -k -H "Authorization: PVEAPIToken=terraform@pve!terraform:TOKEN_SECRET_HERE" \
     https://10.10.1.21:8006/api2/json/version
   ```

### Option 2: Use Password Authentication (Quick Test)

For immediate testing, use root password:

```hcl
provider "proxmox" {
  endpoint = "https://10.10.1.21:8006/"
  username = "root@pam"
  password = "your_root_password"
  insecure = true
}
```

### Option 3: Use Existing Working User

The system already has users in /etc/passwd. We could:
1. Use root@pam with password
2. Or create a dedicated terraform user properly

## Next Steps

1. Choose an option above
2. Test connectivity with our test script
3. Update terraform configuration
4. Deploy simple VM to verify

## Research Finding
Multiple sources confirm that API tokens often have permission issues and username/password is more reliable for initial setup, then migrate to tokens once working.