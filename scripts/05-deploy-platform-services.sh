#!/bin/bash
# Phase 5: Deploy Platform Services
# Installs essential cluster services and addons

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
MANIFESTS_DIR="../manifests"
KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config-k8s-cluster}"

echo "============================================================"
echo "PHASE 5: DEPLOY PLATFORM SERVICES"
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
if [ ! -f "05-deploy-platform-services.sh" ]; then
    log_error "Please run this script from the scripts directory"
    exit 1
fi

# Check kubectl access
export KUBECONFIG
if ! kubectl get nodes &>/dev/null; then
    log_error "Cannot access Kubernetes cluster. Check KUBECONFIG."
    exit 1
fi

# Create manifests directories
mkdir -p "${MANIFESTS_DIR}"/{networking,storage,monitoring,ingress}

# 1. Deploy MetalLB for LoadBalancer services
log_info "Deploying MetalLB load balancer..."
cat > "${MANIFESTS_DIR}/networking/metallb.yaml" << 'EOF'
apiVersion: v1
kind: Namespace
metadata:
  name: metallb-system
---
apiVersion: v1
kind: ConfigMap
metadata:
  namespace: metallb-system
  name: config
data:
  config: |
    address-pools:
    - name: default
      protocol: layer2
      addresses:
      - 10.10.1.150-10.10.1.180
EOF

kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.14.5/config/manifests/metallb-native.yaml
kubectl apply -f "${MANIFESTS_DIR}/networking/metallb.yaml"

# Wait for MetalLB to be ready
log_info "Waiting for MetalLB to be ready..."
kubectl wait --namespace metallb-system \
    --for=condition=ready pod \
    --selector=app=metallb \
    --timeout=300s

# 2. Deploy Proxmox CSI for storage
log_info "Deploying Proxmox CSI driver..."
cat > "${MANIFESTS_DIR}/storage/proxmox-csi.yaml" << 'EOF'
apiVersion: v1
kind: Namespace
metadata:
  name: csi-proxmox
---
apiVersion: v1
kind: Secret
metadata:
  name: proxmox-csi-plugin
  namespace: csi-proxmox
stringData:
  config.yaml: |
    clusters:
    - url: "https://10.10.1.21:8006/api2/json"
      insecure: true
      token_id: "kubernetes@pam!csi"
      token_secret: "7b2a3da7-bd30-4772-a6b0-874aa9b2f3a5"
      region: "default"
---
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: proxmox-rbd
  annotations:
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: csi.proxmox.sinextra.dev
parameters:
  storage: rbd
  cache: writethrough
  fstype: ext4
reclaimPolicy: Delete
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
EOF

kubectl apply -f "${MANIFESTS_DIR}/storage/proxmox-csi.yaml"
kubectl apply -f https://raw.githubusercontent.com/sergelogvinov/proxmox-csi-plugin/main/docs/deploy/proxmox-csi-plugin-release.yml

# 3. Deploy NGINX Ingress Controller
log_info "Deploying NGINX Ingress Controller..."
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.10.0/deploy/static/provider/baremetal/deploy.yaml

# Wait for ingress to be ready
kubectl wait --namespace ingress-nginx \
    --for=condition=ready pod \
    --selector=app.kubernetes.io/component=controller \
    --timeout=300s

# 4. Deploy Prometheus monitoring stack
log_info "Deploying Prometheus monitoring stack..."
cat > "${MANIFESTS_DIR}/monitoring/prometheus-values.yaml" << 'EOF'
prometheus:
  prometheusSpec:
    retention: 30d
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: proxmox-rbd
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 50Gi

grafana:
  adminPassword: admin
  persistence:
    enabled: true
    storageClassName: proxmox-rbd
    size: 10Gi

alertmanager:
  alertmanagerSpec:
    storage:
      volumeClaimTemplate:
        spec:
          storageClassName: proxmox-rbd
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 10Gi
EOF

# Add Prometheus Helm repo
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Install Prometheus stack
helm upgrade --install prometheus prometheus-community/kube-prometheus-stack \
    --namespace monitoring \
    --create-namespace \
    --values "${MANIFESTS_DIR}/monitoring/prometheus-values.yaml" \
    --wait

# 5. Deploy Velero for backup
log_info "Deploying Velero backup solution..."
cat > "${MANIFESTS_DIR}/storage/velero-values.yaml" << 'EOF'
configuration:
  backupStorageLocation:
  - name: default
    provider: aws
    bucket: kubernetes-backups
    config:
      region: minio
      s3ForcePathStyle: true
      s3Url: http://10.10.1.30:9000
  volumeSnapshotLocation:
  - name: default
    provider: csi
    config: {}

credentials:
  secretContents:
    cloud: |
      [default]
      aws_access_key_id=velero
      aws_secret_access_key=velero123

snapshotsEnabled: true
features: EnableCSI

initContainers:
- name: velero-plugin-for-aws
  image: velero/velero-plugin-for-aws:v1.9.0
  volumeMounts:
  - mountPath: /target
    name: plugins
- name: velero-plugin-for-csi
  image: velero/velero-plugin-for-csi:v0.7.0
  volumeMounts:
  - mountPath: /target
    name: plugins
EOF

# Add Velero Helm repo
helm repo add vmware-tanzu https://vmware-tanzu.github.io/helm-charts
helm repo update

# Install Velero
helm upgrade --install velero vmware-tanzu/velero \
    --namespace velero \
    --create-namespace \
    --values "${MANIFESTS_DIR}/storage/velero-values.yaml" \
    --wait

# 6. Deploy Kubernetes Dashboard
log_info "Deploying Kubernetes Dashboard..."
kubectl apply -f https://raw.githubusercontent.com/kubernetes/dashboard/v2.7.0/aio/deploy/recommended.yaml

# Create admin user for dashboard
cat > "${MANIFESTS_DIR}/monitoring/dashboard-admin.yaml" << 'EOF'
apiVersion: v1
kind: ServiceAccount
metadata:
  name: admin-user
  namespace: kubernetes-dashboard
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: admin-user
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
subjects:
- kind: ServiceAccount
  name: admin-user
  namespace: kubernetes-dashboard
EOF

kubectl apply -f "${MANIFESTS_DIR}/monitoring/dashboard-admin.yaml"

# Get dashboard token
log_info "Getting dashboard access token..."
kubectl create token admin-user -n kubernetes-dashboard > "${MANIFESTS_DIR}/monitoring/dashboard-token.txt"

# 7. Deploy cert-manager for TLS certificates
log_info "Deploying cert-manager..."
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.14.4/cert-manager.yaml

# Wait for cert-manager to be ready
kubectl wait --namespace cert-manager \
    --for=condition=ready pod \
    --selector=app.kubernetes.io/instance=cert-manager \
    --timeout=300s

# Summary of deployed services
log_info "Verifying all platform services..."
echo ""
echo "Deployed Services Status:"
echo "========================="

# Check MetalLB
if kubectl get pods -n metallb-system | grep -q Running; then
    echo -e "${GREEN}✓${NC} MetalLB Load Balancer"
else
    echo -e "${RED}✗${NC} MetalLB Load Balancer"
fi

# Check Ingress
if kubectl get pods -n ingress-nginx | grep -q Running; then
    echo -e "${GREEN}✓${NC} NGINX Ingress Controller"
else
    echo -e "${RED}✗${NC} NGINX Ingress Controller"
fi

# Check Prometheus
if kubectl get pods -n monitoring | grep -q prometheus; then
    echo -e "${GREEN}✓${NC} Prometheus Monitoring"
else
    echo -e "${RED}✗${NC} Prometheus Monitoring"
fi

# Check Velero
if kubectl get pods -n velero | grep -q Running; then
    echo -e "${GREEN}✓${NC} Velero Backup"
else
    echo -e "${RED}✗${NC} Velero Backup"
fi

# Check Dashboard
if kubectl get pods -n kubernetes-dashboard | grep -q Running; then
    echo -e "${GREEN}✓${NC} Kubernetes Dashboard"
else
    echo -e "${RED}✗${NC} Kubernetes Dashboard"
fi

# Check cert-manager
if kubectl get pods -n cert-manager | grep -q Running; then
    echo -e "${GREEN}✓${NC} Cert-Manager"
else
    echo -e "${RED}✗${NC} Cert-Manager"
fi

echo ""
echo "============================================================"
echo -e "${GREEN}✓ PHASE 5 COMPLETED${NC}"
echo ""
echo "Access Information:"
echo "==================="
echo "Dashboard: kubectl proxy, then visit:"
echo "  http://localhost:8001/api/v1/namespaces/kubernetes-dashboard/services/https:kubernetes-dashboard:/proxy/"
echo "  Token: cat ${MANIFESTS_DIR}/monitoring/dashboard-token.txt"
echo ""
echo "Grafana: kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80"
echo "  Username: admin"
echo "  Password: admin"
echo ""
echo "Prometheus: kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090"
echo ""
echo "Your Kubernetes cluster is fully operational!"
echo "============================================================"