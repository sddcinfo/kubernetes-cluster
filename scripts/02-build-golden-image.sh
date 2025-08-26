#!/bin/bash
# Create Ubuntu Cloud Image Base VM for Packer Cloning
# Uses properly prepared cloud image with qemu-guest-agent and sysadmin user

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
PROXMOX_HOST="10.10.1.21"
BASE_VM_ID="9002"
MODIFIED_IMAGE="ubuntu-24.04-cloudimg-amd64-modified.img"
VM_NAME="ubuntu-cloud-base"

# Function to print colored output
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

echo "============================================================"
echo "CREATING UBUNTU CLOUD IMAGE BASE VM"
echo "============================================================"

# Check if VM already exists
if ssh root@"$PROXMOX_HOST" "qm status $BASE_VM_ID" &>/dev/null; then
    log_warning "Base VM $BASE_VM_ID already exists, removing..."
    ssh root@"$PROXMOX_HOST" "qm stop $BASE_VM_ID || true && qm destroy $BASE_VM_ID --purge" || {
        log_error "Failed to remove existing base VM"
        exit 1
    }
    log_info "Existing base VM removed"
fi

# Check if modified cloud image exists
if ! ssh root@"$PROXMOX_HOST" "test -f /mnt/rbd-iso/template/images/$MODIFIED_IMAGE"; then
    log_error "Modified cloud image not found: /mnt/rbd-iso/template/images/$MODIFIED_IMAGE"
    log_error "Run ./prepare-cloud-image.sh first"
    exit 1
fi

log_info "Creating base VM from modified cloud image..."

# Create VM with modern EFI configuration and VirtIO RNG for entropy
ssh root@"$PROXMOX_HOST" "qm create $BASE_VM_ID --name $VM_NAME --memory 2048 --cores 2 --net0 virtio,bridge=vmbr0 --scsihw virtio-scsi-pci --ostype l26 --cpu host --agent enabled=1 --machine q35 --bios ovmf --rng0 source=/dev/urandom,max_bytes=1024,period=1000" || {
    log_error "Failed to create base VM"
    exit 1
}

# Disable ROM bar on network interface to prevent iPXE boot
ssh root@"$PROXMOX_HOST" "qm set $BASE_VM_ID --net0 virtio,bridge=vmbr0,rombar=0" || {
    log_warning "Failed to disable network ROM bar, continuing anyway"
}

# Add EFI disk with secure boot disabled for better compatibility
ssh root@"$PROXMOX_HOST" "qm set $BASE_VM_ID --efidisk0 rbd:4,efitype=4m,pre-enrolled-keys=0" || {
    log_error "Failed to add EFI disk"
    exit 1
}

# Import modified cloud image as disk
log_info "Importing modified cloud image as VM disk..."
ssh root@"$PROXMOX_HOST" "qm importdisk $BASE_VM_ID /mnt/rbd-iso/template/images/$MODIFIED_IMAGE rbd --format raw" || {
    log_error "Failed to import cloud image"
    exit 1
}

# Attach the imported disk as scsi0 (following working examples)
ssh root@"$PROXMOX_HOST" "qm set $BASE_VM_ID --scsi0 rbd:vm-$BASE_VM_ID-disk-1" || {
    log_error "Failed to attach disk"
    exit 1
}

# Set boot configuration (order: disk first, then CD-ROM)
ssh root@"$PROXMOX_HOST" "qm set $BASE_VM_ID --boot order=scsi0 --bootdisk scsi0" || {
    log_error "Failed to set boot configuration"
    exit 1
}

# Add cloud-init drive  
ssh root@"$PROXMOX_HOST" "qm set $BASE_VM_ID --ide2 rbd:cloudinit" || {
    log_error "Failed to add cloud-init drive"
    exit 1
}

# Copy SSH key to Proxmox host
if [ -f /home/sysadmin/.ssh/sysadmin_automation_key.pub ]; then
    scp /home/sysadmin/.ssh/sysadmin_automation_key.pub root@"$PROXMOX_HOST":/tmp/
fi

# Configure cloud-init with sysadmin user
ssh root@"$PROXMOX_HOST" "qm set $BASE_VM_ID --ciuser sysadmin --cipassword password --sshkeys /tmp/sysadmin_automation_key.pub --ipconfig0 ip=dhcp" || {
    log_error "Failed to configure cloud-init"
    exit 1
}

# Resize disk to reasonable size
ssh root@"$PROXMOX_HOST" "qm resize $BASE_VM_ID scsi0 32G" || {
    log_warning "Failed to resize disk, continuing anyway"
}

# Convert to template
log_info "Converting to template..."
ssh root@"$PROXMOX_HOST" "qm template $BASE_VM_ID" || {
    log_error "Failed to convert to template"
    exit 1
}

echo ""
echo "============================================================"
echo -e "${GREEN}✓ CLOUD BASE TEMPLATE CREATED SUCCESSFULLY${NC}"
echo "Template details:"
echo "  ID: $BASE_VM_ID"
echo "  Name: $VM_NAME"
echo "  Type: Ubuntu 24.04 Cloud Image Base (with qemu-guest-agent)"
echo "  User: sysadmin (password: password)"
echo "  Ready for Packer cloning"
echo "============================================================"