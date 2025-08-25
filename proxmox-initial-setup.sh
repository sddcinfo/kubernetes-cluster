#!/bin/bash
set -euo pipefail

# Proxmox Initial Setup for Kubernetes Deployment
# This script automates ALL the manual steps we learned through trial and error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$SCRIPT_DIR/proxmox-setup.log"

# Configuration
PROXMOX_HOST="10.10.1.21"
PACKER_USER="packer@pam"
PACKER_TOKEN_NAME="packer"
TERRAFORM_USER="terraform@pam"
TERRAFORM_TOKEN_NAME="terraform"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1" | tee -a "$LOG_FILE"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1" | tee -a "$LOG_FILE"
    exit 1
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1" | tee -a "$LOG_FILE"
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1" | tee -a "$LOG_FILE"
}

check_proxmox_access() {
    log "Checking Proxmox access..."
    
    if ! ping -c 1 "$PROXMOX_HOST" &>/dev/null; then
        error "Cannot reach Proxmox host $PROXMOX_HOST"
    fi
    
    if ! nc -zv "$PROXMOX_HOST" 8006 &>/dev/null; then
        error "Cannot connect to Proxmox web interface on port 8006"
    fi
    
    success "Proxmox host is accessible"
}

create_packer_user() {
    log "Creating Packer user and permissions..."
    
    # Create packer user (ignore if exists)
    if pveum user list | grep -q "$PACKER_USER"; then
        warning "User $PACKER_USER already exists, skipping creation"
    else
        pveum user add "$PACKER_USER" --password "PackerUser123!" || error "Failed to create packer user"
        success "Created packer user"
    fi
    
    # Create PackerRole with ALL required permissions (learned through trial and error)
    if pveum role list | grep -q "PackerRole"; then
        warning "PackerRole already exists, updating permissions"
        pveum role mod PackerRole -privs "VM.Allocate,VM.Clone,VM.Config.CDROM,VM.Config.CPU,VM.Config.Disk,VM.Config.HWType,VM.Config.Memory,VM.Config.Network,VM.Config.Options,VM.Monitor,VM.Audit,VM.PowerMgmt,VM.GuestAgent.Audit,VM.GuestAgent.Unrestricted,Datastore.AllocateSpace,Datastore.Audit,Pool.Allocate,Datastore.AllocateTemplate"
    else
        pveum role add PackerRole -privs "VM.Allocate,VM.Clone,VM.Config.CDROM,VM.Config.CPU,VM.Config.Disk,VM.Config.HWType,VM.Config.Memory,VM.Config.Network,VM.Config.Options,VM.Monitor,VM.Audit,VM.PowerMgmt,VM.GuestAgent.Audit,VM.GuestAgent.Unrestricted,Datastore.AllocateSpace,Datastore.Audit,Pool.Allocate,Datastore.AllocateTemplate"
    fi
    
    # Assign role to user
    pveum aclmod / -user "$PACKER_USER" -role PackerRole || warning "Failed to assign role (may already be assigned)"
    
    # Create API token with privilege separation DISABLED (critical!)
    if pveum user token list "$PACKER_USER" 2>/dev/null | grep -q "$PACKER_TOKEN_NAME"; then
        warning "Packer token already exists, skipping creation"
        log "Existing token ID: $PACKER_USER!$PACKER_TOKEN_NAME"
    else
        log "Creating API token..."
        TOKEN_OUTPUT=$(pveum user token add "$PACKER_USER" "$PACKER_TOKEN_NAME" --privsep=0)
        PACKER_TOKEN=$(echo "$TOKEN_OUTPUT" | grep -o '[a-f0-9-]\{36\}' | head -1)
        
        if [ -n "$PACKER_TOKEN" ]; then
            success "Created Packer API token"
            log "IMPORTANT: Save this token: $PACKER_USER!$PACKER_TOKEN_NAME=$PACKER_TOKEN"
            echo "$PACKER_USER!$PACKER_TOKEN_NAME=$PACKER_TOKEN" > "$SCRIPT_DIR/packer-token.txt"
            chmod 600 "$SCRIPT_DIR/packer-token.txt"
        else
            error "Failed to extract API token from output"
        fi
    fi
}

create_terraform_user() {
    log "Creating Terraform user and permissions..."
    
    # Create terraform user (ignore if exists)
    if pveum user list | grep -q "$TERRAFORM_USER"; then
        warning "User $TERRAFORM_USER already exists, skipping creation"
    else
        pveum user add "$TERRAFORM_USER" --password "TerraformUser123!" || error "Failed to create terraform user"
        success "Created terraform user"
    fi
    
    # Create TerraformRole with comprehensive permissions
    if pveum role list | grep -q "TerraformRole"; then
        warning "TerraformRole already exists, updating permissions"
        pveum role mod TerraformRole -privs "VM.Allocate,VM.Clone,VM.Config.CDROM,VM.Config.CPU,VM.Config.Disk,VM.Config.HWType,VM.Config.Memory,VM.Config.Network,VM.Config.Options,VM.Monitor,VM.Audit,VM.PowerMgmt,VM.Console,VM.Migrate,Datastore.AllocateSpace,Datastore.Audit,Pool.Allocate,SDN.Use,Sys.Audit"
    else
        pveum role add TerraformRole -privs "VM.Allocate,VM.Clone,VM.Config.CDROM,VM.Config.CPU,VM.Config.Disk,VM.Config.HWType,VM.Config.Memory,VM.Config.Network,VM.Config.Options,VM.Monitor,VM.Audit,VM.PowerMgmt,VM.Console,VM.Migrate,Datastore.AllocateSpace,Datastore.Audit,Pool.Allocate,SDN.Use,Sys.Audit"
    fi
    
    # Assign role to user
    pveum aclmod / -user "$TERRAFORM_USER" -role TerraformRole || warning "Failed to assign role (may already be assigned)"
    
    # Create API token with privilege separation DISABLED
    if pveum user token list "$TERRAFORM_USER" 2>/dev/null | grep -q "$TERRAFORM_TOKEN_NAME"; then
        warning "Terraform token already exists, skipping creation"
        log "Existing token ID: $TERRAFORM_USER!$TERRAFORM_TOKEN_NAME"
    else
        log "Creating Terraform API token..."
        TOKEN_OUTPUT=$(pveum user token add "$TERRAFORM_USER" "$TERRAFORM_TOKEN_NAME" --privsep=0)
        TERRAFORM_TOKEN=$(echo "$TOKEN_OUTPUT" | grep -o '[a-f0-9-]\{36\}' | head -1)
        
        if [ -n "$TERRAFORM_TOKEN" ]; then
            success "Created Terraform API token"
            log "IMPORTANT: Save this token: $TERRAFORM_USER!$TERRAFORM_TOKEN_NAME=$TERRAFORM_TOKEN"
            echo "$TERRAFORM_USER!$TERRAFORM_TOKEN_NAME=$TERRAFORM_TOKEN" > "$SCRIPT_DIR/terraform-token.txt"
            chmod 600 "$SCRIPT_DIR/terraform-token.txt"
        else
            error "Failed to extract Terraform API token from output"
        fi
    fi
}

test_api_connectivity() {
    log "Testing API connectivity..."
    
    # Test with existing packer token if available
    if [ -f "$SCRIPT_DIR/packer-token.txt" ]; then
        PACKER_TOKEN_FULL=$(cat "$SCRIPT_DIR/packer-token.txt")
        log "Testing API with packer token..."
        
        RESPONSE=$(curl -k -s -H "Authorization: PVEAPIToken=$PACKER_TOKEN_FULL" \
            "https://$PROXMOX_HOST:8006/api2/json/version" 2>/dev/null || echo "")
        
        if echo "$RESPONSE" | grep -q "version"; then
            success "Packer API token is working!"
            VERSION=$(echo "$RESPONSE" | jq -r '.data.version' 2>/dev/null || echo "unknown")
            log "Proxmox version: $VERSION"
        else
            error "Packer API token test failed. Response: $RESPONSE"
        fi
    else
        warning "No packer token file found, skipping API test"
    fi
}

verify_storage() {
    log "Verifying storage configuration..."
    
    # Check if required storage pools exist
    STORAGE_LIST=$(pvesm status 2>/dev/null || echo "")
    
    if echo "$STORAGE_LIST" | grep -q "local"; then
        success "Local storage available"
    else
        warning "Local storage not found"
    fi
    
    if echo "$STORAGE_LIST" | grep -q "rbd"; then
        success "RBD (Ceph) storage available"
    else
        warning "RBD storage not found - using local storage only"
    fi
}

setup_ssh_access() {
    log "Configuring SSH access for automation..."
    
    # Ensure SSH keys exist
    if [ ! -f "$HOME/.ssh/id_rsa" ]; then
        log "Generating SSH key pair..."
        ssh-keygen -t rsa -b 4096 -f "$HOME/.ssh/id_rsa" -N "" -C "proxmox-automation"
        success "Generated SSH key pair"
    else
        success "SSH key pair already exists"
    fi
    
    # Add local host to known_hosts if not present
    if ! ssh-keyscan -t ed25519 localhost 2>/dev/null | grep -q "localhost"; then
        ssh-keyscan -t ed25519 localhost >> "$HOME/.ssh/known_hosts" 2>/dev/null || warning "Could not add localhost to known_hosts"
    fi
    
    # Add Proxmox host to known_hosts
    if ! ssh-keyscan -t ed25519 "$PROXMOX_HOST" 2>/dev/null | grep -q "$PROXMOX_HOST"; then
        ssh-keyscan -t ed25519 "$PROXMOX_HOST" >> "$HOME/.ssh/known_hosts" 2>/dev/null || warning "Could not add $PROXMOX_HOST to known_hosts"
    fi
}

create_summary() {
    log "Creating setup summary..."
    
    cat > "$SCRIPT_DIR/proxmox-setup-summary.txt" << EOF
Proxmox Kubernetes Setup Summary
Generated: $(date)

API Endpoints:
- Proxmox Host: $PROXMOX_HOST:8006
- API URL: https://$PROXMOX_HOST:8006/api2/json

Users Created:
- Packer User: $PACKER_USER (Role: PackerRole)
- Terraform User: $TERRAFORM_USER (Role: TerraformRole)

Token Files:
- Packer: $SCRIPT_DIR/packer-token.txt
- Terraform: $SCRIPT_DIR/terraform-token.txt

Next Steps:
1. Run the main deployment script: ./k8s_proxmox_deployer.py
2. Or use individual components:
   - Packer: Use token from packer-token.txt
   - Terraform: Use token from terraform-token.txt

IMPORTANT: Keep token files secure and backed up!
EOF

    success "Setup summary created: $SCRIPT_DIR/proxmox-setup-summary.txt"
}

main() {
    log "Starting Proxmox initial setup for Kubernetes deployment..."
    log "This script captures all manual steps learned through trial and error"
    
    # Check if running on Proxmox node
    if [ ! -f "/etc/pve/nodes" ] && [ ! -d "/etc/pve" ]; then
        error "This script must be run on a Proxmox VE node"
    fi
    
    check_proxmox_access
    create_packer_user
    create_terraform_user
    test_api_connectivity
    verify_storage
    setup_ssh_access
    create_summary
    
    success "Proxmox initial setup completed successfully!"
    log "Log file: $LOG_FILE"
    log "Summary: $SCRIPT_DIR/proxmox-setup-summary.txt"
    
    cat "$SCRIPT_DIR/proxmox-setup-summary.txt"
}

# Run main function
main "$@"