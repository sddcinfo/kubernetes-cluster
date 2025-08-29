#!/bin/bash

# Setup script for Kubespray download cache optimization
# This script creates persistent cache directories and configures permissions

set -e

echo "Setting up Kubespray download cache directories..."

# Define cache directories
CACHE_BASE="/var/cache/kubespray"
RELEASES_DIR="${CACHE_BASE}/releases"
DOWNLOAD_CACHE="${CACHE_BASE}/downloads"
IMAGES_CACHE="${CACHE_BASE}/images"

# Create cache directories with proper permissions
echo "Creating cache directories..."
sudo mkdir -p "${RELEASES_DIR}"
sudo mkdir -p "${DOWNLOAD_CACHE}"
sudo mkdir -p "${IMAGES_CACHE}"

# Set ownership and permissions properly
sudo chown -R ${USER}:${USER} "${CACHE_BASE}"
sudo chmod -R 755 "${CACHE_BASE}"

# Create symlinks from default locations to persistent cache
echo "Creating symlinks to persistent cache..."

# Backup existing directories if they exist and contain data
if [ -d "/tmp/releases" ] && [ "$(ls -A /tmp/releases 2>/dev/null)" ]; then
    echo "Backing up existing /tmp/releases..."
    sudo cp -r /tmp/releases/* "${RELEASES_DIR}/" 2>/dev/null || true
fi

if [ -d "/tmp/kubespray_cache" ] && [ "$(ls -A /tmp/kubespray_cache 2>/dev/null)" ]; then
    echo "Backing up existing /tmp/kubespray_cache..."
    sudo cp -r /tmp/kubespray_cache/* "${DOWNLOAD_CACHE}/" 2>/dev/null || true
fi

# Remove old directories and create direct directories (not symlinks to avoid permission issues)
sudo rm -rf /tmp/releases /tmp/kubespray_cache
sudo mkdir -p /tmp/releases /tmp/kubespray_cache
sudo chown -R ${USER}:${USER} /tmp/releases /tmp/kubespray_cache
sudo chmod -R 755 /tmp/releases /tmp/kubespray_cache

# Create cache info file
cat > "${CACHE_BASE}/cache-info.txt" << EOF
Kubespray Download Cache Information
=====================================
Created: $(date)
User: ${USER}

Cache Directories:
- Releases: ${RELEASES_DIR}
- Downloads: ${DOWNLOAD_CACHE}
- Images: ${IMAGES_CACHE}

Directories:
- /tmp/releases (local cache)
- /tmp/kubespray_cache (local cache)
- Persistent cache: ${CACHE_BASE}

Configuration:
- download_run_once: true
- download_keep_remote_cache: true
- download_force_cache: true

To clear cache:
  sudo rm -rf ${CACHE_BASE}/*

To check cache size:
  du -sh ${CACHE_BASE}
EOF

echo "Cache setup complete!"
echo ""
echo "Cache information:"
cat "${CACHE_BASE}/cache-info.txt"
echo ""
echo "Current cache size:"
du -sh "${CACHE_BASE}" 2>/dev/null || echo "Empty"