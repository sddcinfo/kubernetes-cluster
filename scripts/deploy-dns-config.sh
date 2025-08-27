#!/bin/bash
# Deploy DNS Configuration for Kubernetes Cluster
# This script adds the Kubernetes DNS configuration to the existing dnsmasq setup

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
DNS_SERVER="10.10.1.1"
DNS_CONFIG_SOURCE="configs/dnsmasq.d/kubernetes.conf"
DNS_CONFIG_TARGET="/etc/dnsmasq.d/kubernetes.conf"

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

log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

echo "========================================================"
echo "DEPLOYING KUBERNETES DNS CONFIGURATION"
echo "========================================================"

# Check if source config exists
if [[ ! -f "$DNS_CONFIG_SOURCE" ]]; then
    log_error "Source DNS configuration not found: $DNS_CONFIG_SOURCE"
    exit 1
fi

log_info "Source configuration found: $DNS_CONFIG_SOURCE"

# Check if we can reach the DNS server
log_step "Testing connectivity to DNS server..."
if ! ping -c 1 "$DNS_SERVER" >/dev/null 2>&1; then
    log_error "Cannot reach DNS server at $DNS_SERVER"
    exit 1
fi

log_info "DNS server $DNS_SERVER is reachable"

# Backup existing configuration if it exists
log_step "Backing up existing configuration..."
if sudo test -f "$DNS_CONFIG_TARGET"; then
    sudo cp "$DNS_CONFIG_TARGET" "${DNS_CONFIG_TARGET}.backup.$(date +%Y%m%d-%H%M%S)"
    log_info "Existing configuration backed up"
else
    log_info "No existing Kubernetes DNS configuration found"
fi

# Copy new configuration
log_step "Deploying new Kubernetes DNS configuration..."
sudo cp "$DNS_CONFIG_SOURCE" "$DNS_CONFIG_TARGET"
sudo chmod 644 "$DNS_CONFIG_TARGET"
sudo chown root:root "$DNS_CONFIG_TARGET"

log_info "Configuration deployed to $DNS_CONFIG_TARGET"

# Validate configuration syntax
log_step "Validating dnsmasq configuration..."
if sudo dnsmasq --test --conf-file=/etc/dnsmasq.conf --conf-dir=/etc/dnsmasq.d >/dev/null 2>&1; then
    log_info "Configuration syntax is valid"
else
    log_error "Configuration syntax is invalid!"
    sudo dnsmasq --test --conf-file=/etc/dnsmasq.conf --conf-dir=/etc/dnsmasq.d
    exit 1
fi

# Check if dnsmasq is running
log_step "Checking dnsmasq service status..."
if systemctl is-active --quiet dnsmasq; then
    log_info "dnsmasq service is running"
    
    # Reload configuration
    log_step "Reloading dnsmasq configuration..."
    if sudo systemctl reload dnsmasq; then
        log_info "dnsmasq configuration reloaded successfully"
    else
        log_error "Failed to reload dnsmasq configuration"
        exit 1
    fi
else
    log_warning "dnsmasq service is not running"
    log_step "Starting dnsmasq service..."
    if sudo systemctl start dnsmasq; then
        log_info "dnsmasq service started successfully"
    else
        log_error "Failed to start dnsmasq service"
        exit 1
    fi
fi

# Test DNS resolution
log_step "Testing DNS resolution..."
test_records=(
    "k8s-vip.sddc.info"
    "k8s-control-1.sddc.info"
    "k8s-worker-1.sddc.info"
    "ingress.k8s.sddc.info"
)

all_tests_passed=true

for record in "${test_records[@]}"; do
    if nslookup "$record" "$DNS_SERVER" >/dev/null 2>&1; then
        log_info "✓ DNS resolution working for $record"
    else
        log_warning "✗ DNS resolution failed for $record"
        all_tests_passed=false
    fi
done

# Summary
echo ""
echo "========================================================"
if $all_tests_passed; then
    log_info "✓ DNS CONFIGURATION DEPLOYMENT COMPLETED SUCCESSFULLY"
else
    log_warning "⚠ DNS CONFIGURATION DEPLOYED WITH SOME RESOLUTION ISSUES"
fi
echo "========================================================"
echo "Configuration file: $DNS_CONFIG_TARGET"
echo "DNS server: $DNS_SERVER"
echo "Test with: nslookup k8s-vip.sddc.info $DNS_SERVER"
echo "========================================================"