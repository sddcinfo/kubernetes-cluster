#!/bin/bash
# Prepare Ubuntu Cloud Image with qemu-guest-agent for Packer use
# Based on working examples from dev.to and austinsnerdythings.com

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

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

# Configuration
PROXMOX_HOST="10.10.1.21"
CLOUD_IMAGE="ubuntu-24.04-cloudimg-amd64.img"
MODIFIED_IMAGE="ubuntu-24.04-cloudimg-amd64-modified.img"
IMAGE_URL="https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"

echo "============================================================"
echo "PREPARING UBUNTU CLOUD IMAGE FOR PACKER"
echo "============================================================"

log_info "Installing required tools on Proxmox host..."
ssh root@"$PROXMOX_HOST" "apt-get update >/dev/null 2>&1 && apt-get install -y libguestfs-tools >/dev/null 2>&1" || {
    log_error "Failed to install libguestfs-tools"
    exit 1
}

log_info "Downloading Ubuntu 24.04 Noble cloud image..."
ssh root@"$PROXMOX_HOST" "cd /mnt/rbd-iso/template/images && wget -q -O $MODIFIED_IMAGE $IMAGE_URL" || {
    log_error "Failed to download cloud image"
    exit 1
}

log_info "Installing qemu-guest-agent and EFI boot support in cloud image..."
ssh root@"$PROXMOX_HOST" "cd /mnt/rbd-iso/template/images && virt-customize --install qemu-guest-agent,grub-efi-amd64,grub-efi-amd64-signed,shim-signed -a $MODIFIED_IMAGE" || {
    log_error "Failed to install qemu-guest-agent and EFI boot support"
    exit 1
}

log_info "Resetting machine-id to avoid DHCP conflicts..."
ssh root@"$PROXMOX_HOST" "cd /mnt/rbd-iso/template/images && virt-sysprep -a $MODIFIED_IMAGE" || {
    log_warning "virt-sysprep failed, continuing anyway"
}

log_info "Creating sysadmin user in cloud image..."
ssh root@"$PROXMOX_HOST" "cd /mnt/rbd-iso/template/images && virt-customize -a $MODIFIED_IMAGE --run-command 'useradd -m -s /bin/bash sysadmin'" || {
    log_error "Failed to create sysadmin user"
    exit 1
}

log_info "Setting up sysadmin user with sudo privileges..."
ssh root@"$PROXMOX_HOST" "cd /mnt/rbd-iso/template/images && virt-customize -a $MODIFIED_IMAGE --run-command 'usermod -aG sudo sysadmin'" || {
    log_error "Failed to add sysadmin to sudo group"
    exit 1
}

log_info "Setting sysadmin password..."
ssh root@"$PROXMOX_HOST" "cd /mnt/rbd-iso/template/images && virt-customize -a $MODIFIED_IMAGE --run-command 'echo \"sysadmin:password\" | chpasswd'" || {
    log_error "Failed to set sysadmin password"
    exit 1
}

log_info "Injecting SSH key for sysadmin user..."
scp /home/sysadmin/.ssh/sysadmin_automation_key.pub root@"$PROXMOX_HOST":/tmp/
ssh root@"$PROXMOX_HOST" "cd /mnt/rbd-iso/template/images && virt-customize -a $MODIFIED_IMAGE --ssh-inject sysadmin:file:/tmp/sysadmin_automation_key.pub" || {
    log_error "Failed to inject SSH key"
    exit 1
}

log_info "Setting up sudoers for sysadmin..."
ssh root@"$PROXMOX_HOST" "cd /mnt/rbd-iso/template/images && virt-customize -a $MODIFIED_IMAGE --run-command 'echo \"sysadmin ALL=(ALL) NOPASSWD:ALL\" > /etc/sudoers.d/sysadmin'" || {
    log_error "Failed to setup sudoers"
    exit 1
}

log_info "Fixing EFI boot partition and installing GRUB properly..."
ssh root@"$PROXMOX_HOST" "cd /mnt/rbd-iso/template/images && virt-customize -a $MODIFIED_IMAGE --run-command 'mkdir -p /boot/efi && mount /dev/sda15 /boot/efi || mount /dev/vda15 /boot/efi'" || {
    log_warning "Failed to mount EFI partition, continuing anyway"
}

log_info "Installing and configuring EFI bootloader..."
ssh root@"$PROXMOX_HOST" "cd /mnt/rbd-iso/template/images && virt-customize -a $MODIFIED_IMAGE --run-command 'update-grub && grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=ubuntu --recheck'" || {
    log_warning "EFI bootloader installation failed, continuing anyway"
}

log_info "Creating UEFI fallback bootloader..."
ssh root@"$PROXMOX_HOST" "cd /mnt/rbd-iso/template/images && virt-customize -a $MODIFIED_IMAGE --run-command 'mkdir -p /boot/efi/EFI/BOOT && cp /boot/efi/EFI/ubuntu/grubx64.efi /boot/efi/EFI/BOOT/BOOTX64.EFI 2>/dev/null || cp /boot/efi/EFI/ubuntu/shimx64.efi /boot/efi/EFI/BOOT/BOOTX64.EFI'" || {
    log_warning "EFI fallback bootloader creation failed, continuing anyway"
}

echo ""
echo "============================================================"
echo -e "${GREEN}✓ CLOUD IMAGE PREPARED SUCCESSFULLY${NC}"
echo "Modified image: $MODIFIED_IMAGE"
echo "Ready for Proxmox template creation"
echo "============================================================"