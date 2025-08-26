#!/bin/bash
# Phase 2: Build Vanilla Golden Image with Packer
# Creates a simple Ubuntu 24.04.3 template with qemu-guest-agent

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
PACKER_DIR="../packer"
TEMPLATE_NAME="ubuntu-2404-vanilla-golden"
TEMPLATE_ID="9000"
UBUNTU_VERSION="24.04.3"
PACKER_TEMPLATE="ubuntu-vanilla-golden.pkr.hcl"
PROXMOX_HOST="10.10.1.21"

echo "============================================================"
echo "PHASE 2: BUILD VANILLA GOLDEN IMAGE"
echo "============================================================"

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

# Check if running from scripts directory
if [ ! -f "02-build-vanilla-golden.sh" ]; then
    log_error "Please run this script from the scripts directory"
    exit 1
fi

# Check Packer template exists
log_info "Checking for Packer template..."
if [ ! -f "${PACKER_DIR}/${PACKER_TEMPLATE}" ]; then
    log_error "Packer template not found: ${PACKER_DIR}/${PACKER_TEMPLATE}"
    exit 1
fi

log_info "Using Packer template: ${PACKER_DIR}/${PACKER_TEMPLATE}"

# Validate Packer template
log_info "Validating Packer template..."
cd "$PACKER_DIR"
if packer validate "$PACKER_TEMPLATE"; then
    log_info "Packer template is valid"
else
    log_error "Packer template validation failed"
    exit 1
fi

# Check if template already exists and remove it (fresh installation handling)
log_info "Checking for existing template..."
if ssh root@"$PROXMOX_HOST" "qm status $TEMPLATE_ID" &>/dev/null; then
    log_warning "Template $TEMPLATE_ID already exists, removing..."
    ssh root@"$PROXMOX_HOST" "qm destroy $TEMPLATE_ID --purge" || {
        log_error "Failed to remove existing template"
        exit 1
    }
    log_info "Existing template removed"
else
    log_info "No existing template found (fresh installation)"
fi

# Build the vanilla golden image
log_info "Building vanilla golden image with Packer..."
log_info "This will download Ubuntu ${UBUNTU_VERSION} ISO and create the template"
log_info "This may take 15-20 minutes..."
echo ""

if packer build "$PACKER_TEMPLATE"; then
    log_info "Vanilla golden image build completed successfully!"
    
    echo ""
    echo "============================================================"
    echo -e "${GREEN}✓ PHASE 2 COMPLETED SUCCESSFULLY${NC}"
    echo "Template details:"
    echo "  ID: $TEMPLATE_ID"
    echo "  Name: $TEMPLATE_NAME" 
    echo "  Type: Vanilla Ubuntu ${UBUNTU_VERSION} with qemu-guest-agent"
    echo ""
    echo "Template is ready for cloning or further customization"
    echo "============================================================"
else
    log_error "Packer build failed"
    echo ""
    echo "Common issues:"
    echo "  - Network connectivity problems"
    echo "  - Proxmox authentication issues" 
    echo "  - Storage space on Proxmox"
    echo "  - ISO download problems"
    echo ""
    echo "Check the Packer logs above for specific error details"
    exit 1
fi