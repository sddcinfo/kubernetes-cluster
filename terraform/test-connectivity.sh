#!/bin/bash

echo "=== Testing Proxmox Connectivity Before Terraform ==="

PROXMOX_HOST="10.10.1.21"
API_TOKEN="packer@pam!packer:7b2a3da7-bd30-4772-a6b0-874aa9b2f3a5"

echo "1. Testing basic connectivity..."
ping -c 1 $PROXMOX_HOST > /dev/null
if [ $? -eq 0 ]; then
    echo "✓ Host is reachable"
else
    echo "✗ Host is not reachable"
    exit 1
fi

echo "2. Testing HTTPS port..."
nc -zv $PROXMOX_HOST 8006 2>&1 | grep -q "succeeded"
if [ $? -eq 0 ]; then
    echo "✓ Port 8006 is open"
else
    echo "✗ Port 8006 is not accessible"
    exit 1
fi

echo "3. Testing API version endpoint..."
response=$(curl -k -s -H "Authorization: PVEAPIToken=$API_TOKEN" \
    "https://$PROXMOX_HOST:8006/api2/json/version" 2>/dev/null)

if echo "$response" | grep -q "version"; then
    echo "✓ API is responding"
    echo "   Version info: $(echo $response | jq -r '.data.version' 2>/dev/null || echo 'unknown')"
else
    echo "✗ API is not responding properly"
    echo "   Response: $response"
    exit 1
fi

echo "4. Testing node list..."
nodes=$(curl -k -s -H "Authorization: PVEAPIToken=$API_TOKEN" \
    "https://$PROXMOX_HOST:8006/api2/json/nodes" 2>/dev/null)

if echo "$nodes" | grep -q "node1"; then
    echo "✓ Can access node list"
else
    echo "✗ Cannot access node list"
    echo "   Response: $nodes"
fi

echo "5. Testing VM list for node1..."
vms=$(curl -k -s -H "Authorization: PVEAPIToken=$API_TOKEN" \
    "https://$PROXMOX_HOST:8006/api2/json/nodes/node1/qemu" 2>/dev/null)

if echo "$vms" | grep -q "data"; then
    echo "✓ Can access VM list"
    vm_count=$(echo "$vms" | jq '.data | length' 2>/dev/null || echo "unknown")
    echo "   Found $vm_count VMs"
else
    echo "✗ Cannot access VM list"
    echo "   Response: $vms"
fi

echo "6. Testing template 9003 exists..."
template_info=$(curl -k -s -H "Authorization: PVEAPIToken=$API_TOKEN" \
    "https://$PROXMOX_HOST:8006/api2/json/nodes/node1/qemu/9003/config" 2>/dev/null)

if echo "$template_info" | grep -q "template.*1"; then
    echo "✓ Template 9003 exists and is marked as template"
else
    echo "⚠ Template 9003 may not exist or not be a template"
    echo "   Response: $template_info"
fi

echo ""
echo "=== Connectivity Test Complete ==="
echo "If all tests passed, Terraform should work."
echo "If any failed, fix those issues before running Terraform."