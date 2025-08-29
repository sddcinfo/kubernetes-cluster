#!/bin/bash

# Robust cache setup script for all Kubernetes cluster nodes
# This ensures proper permissions and directory structure for Kubespray downloads

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
KUBESPRAY_DIR="${PROJECT_ROOT}/kubespray"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

echo "========================================="
echo "Cluster-wide Cache Setup"
echo "========================================="

# Check if Kubespray is available
if [ ! -d "$KUBESPRAY_DIR" ]; then
    print_error "Kubespray not found. Run setup-kubespray.sh first."
    exit 1
fi

# Setup cache on all nodes
print_status "Setting up cache directories on all cluster nodes..."

cd "$KUBESPRAY_DIR"
source venv/bin/activate

# Create minimal cache setup script for remote execution
REMOTE_SCRIPT=$(cat << 'EOF'
#!/bin/bash
set -e

# Define cache directories only - Kubespray handles Kubernetes directories natively
CACHE_BASE="/var/cache/kubespray"
TMP_RELEASES="/tmp/releases"
TMP_CACHE="/tmp/kubespray_cache"

# Create persistent cache directories for download optimization
sudo mkdir -p "${CACHE_BASE}/releases" "${CACHE_BASE}/downloads" "${CACHE_BASE}/images"
sudo chown -R sysadmin:sysadmin "${CACHE_BASE}"
sudo chmod -R 755 "${CACHE_BASE}"

# Create temporary cache directories for Kubespray downloads
sudo rm -rf "${TMP_RELEASES}" "${TMP_CACHE}"
sudo mkdir -p "${TMP_RELEASES}" "${TMP_CACHE}"
sudo chown -R sysadmin:sysadmin "${TMP_RELEASES}" "${TMP_CACHE}"
sudo chmod -R 755 "${TMP_RELEASES}" "${TMP_CACHE}"

# Create subdirectories that Kubespray download process expects
sudo mkdir -p "${TMP_RELEASES}/images"
sudo chown -R sysadmin:sysadmin "${TMP_RELEASES}/images"
sudo chmod -R 755 "${TMP_RELEASES}/images"

echo "Cache directories setup complete on $(hostname)"
echo "Kubespray will handle Kubernetes, CNI, and system directories with proper become privileges"
EOF
)

# Execute on all nodes
ansible -i inventory/proxmox-cluster/inventory.ini all -m shell -a "$REMOTE_SCRIPT" || {
    print_error "Failed to setup cache on some nodes. Attempting alternative method..."
    
    # Alternative: setup cache directories only (Kubespray handles the rest)
    ansible -i inventory/proxmox-cluster/inventory.ini all -m shell -a "sudo mkdir -p /var/cache/kubespray/releases /var/cache/kubespray/downloads /var/cache/kubespray/images"
    ansible -i inventory/proxmox-cluster/inventory.ini all -m shell -a "sudo mkdir -p /tmp/releases/images /tmp/kubespray_cache"
    ansible -i inventory/proxmox-cluster/inventory.ini all -m shell -a "sudo chown -R sysadmin:sysadmin /var/cache/kubespray /tmp/releases /tmp/kubespray_cache"
    ansible -i inventory/proxmox-cluster/inventory.ini all -m shell -a "sudo chmod -R 755 /var/cache/kubespray /tmp/releases /tmp/kubespray_cache"
}

print_status "Verifying cache setup..."

# Verify setup on all nodes
ansible -i inventory/proxmox-cluster/inventory.ini all -m shell -a "ls -la /tmp/releases/ && ls -la /var/cache/kubespray/" | grep -E "(SUCCESS|CHANGED)" && {
    print_status "✅ Cache setup completed successfully on all nodes!"
} || {
    print_warning "⚠️  Some nodes may have setup issues. Check manually if needed."
}

echo ""
echo "Cache directories are now properly configured for optimized downloads."
echo "You can now run: ./deploy-cluster.sh deploy"