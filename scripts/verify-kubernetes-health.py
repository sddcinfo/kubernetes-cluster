#!/home/sysadmin/claude/kubernetes-cluster/kubespray/venv/bin/python

import argparse
import os
import requests
import base64
from kubernetes import client, config

def check_node_health(verbose=False):
    """Checks the health of all nodes in the cluster."""
    try:
        api = client.CoreV1Api()
        nodes = api.list_node()
        unhealthy_nodes = []
        healthy_nodes = []
        for node in nodes.items:
            is_healthy = True
            for condition in node.status.conditions:
                if condition.type == "Ready":
                    if condition.status != "True":
                        unhealthy_nodes.append((node.metadata.name, condition.reason, condition.message))
                        is_healthy = False
            if is_healthy:
                healthy_nodes.append(node.metadata.name)

        if verbose:
            print("\n--- All Nodes ---")
            for node in nodes.items:
                print(f"- {node.metadata.name}")
                for condition in node.status.conditions:
                    print(f"  - {condition.type}: {condition.status}")

        return unhealthy_nodes, healthy_nodes
    except Exception as e:
        print(f"Error checking node health: {e}")
        return None, None

def check_pod_health(verbose=False):
    """Checks the health of all pods in all namespaces."""
    try:
        api = client.CoreV1Api()
        pods = api.list_pod_for_all_namespaces()
        unhealthy_pods = []
        healthy_pods = []
        for pod in pods.items:
            is_healthy = True
            if pod.status.phase not in ["Running", "Succeeded"]:
                unhealthy_pods.append((pod.metadata.namespace, pod.metadata.name, pod.status.phase, pod.status.reason, pod.status.message))
                is_healthy = False
            else:
                if pod.status.container_statuses:
                    for container_status in pod.status.container_statuses:
                        if not container_status.ready:
                            unhealthy_pods.append((pod.metadata.namespace, pod.metadata.name, "NotReady", container_status.state.waiting.reason if container_status.state.waiting else "N/A", container_status.state.waiting.message if container_status.state.waiting else "N/A"))
                            is_healthy = False
            if is_healthy:
                healthy_pods.append((pod.metadata.namespace, pod.metadata.name))

        if verbose:
            print("\n--- All Pods ---")
            for pod in pods.items:
                print(f"- Namespace: {pod.metadata.namespace}, Pod: {pod.metadata.name}, Phase: {pod.status.phase}")

        return unhealthy_pods, healthy_pods
    except Exception as e:
        print(f"Error checking pod health: {e}")
        return None, None

def test_argocd_login():
    """Tests login to ArgoCD."""
    print("\n--- Testing ArgoCD Login ---")
    try:
        # First, try the standard password
        standard_password = os.environ.get("K8S_APP_PASSWORD", "")
        if not standard_password:
            print("K8S_APP_PASSWORD env var not set, skipping password test")
            return
        url = "https://argocd.apps.sddc.info/api/v1/session"
        payload = {"username": "admin", "password": standard_password}
        response = requests.post(url, json=payload, verify=False)
        if response.status_code == 200:
            print("ArgoCD login successful with standard password.")
            return

        # If the standard password fails, try the initial admin secret
        v1 = client.CoreV1Api()
        secret = v1.read_namespaced_secret("argocd-initial-admin-secret", "argocd")
        password = base64.b64decode(secret.data["password"]).decode("utf-8")
        payload = {"username": "admin", "password": password}
        response = requests.post(url, json=payload, verify=False)
        if response.status_code == 200:
            print("ArgoCD login successful with initial admin secret.")
        else:
            print(f"ArgoCD login failed. Status code: {response.status_code}")
            print(f"Response: {response.text}")
    except Exception as e:
        print(f"Error testing ArgoCD login: {e}")


def test_grafana_login():
    """Tests login to Grafana."""
    print("\n--- Testing Grafana Login ---")
    try:
        v1 = client.CoreV1Api()
        secret = v1.read_namespaced_secret("kube-prometheus-stack-grafana", "monitoring")
        password = base64.b64decode(secret.data["admin-password"]).decode("utf-8")
        url = "https://grafana.apps.sddc.info/login"
        payload = {"user": "admin", "password": password}
        response = requests.post(url, json=payload, verify=False)
        if response.status_code == 200:
            print("Grafana login successful.")
        else:
            print(f"Grafana login failed. Status code: {response.status_code}")
    except Exception as e:
        print(f"Error testing Grafana login: {e}")

def test_prometheus_access():
    """Tests access to Prometheus."""
    print("\n--- Testing Prometheus Access ---")
    try:
        url = "http://prometheus.apps.sddc.info"
        response = requests.get(url)
        if response.status_code == 200:
            print("Prometheus access successful.")
        else:
            print(f"Prometheus access failed. Status code: {response.status_code}")
    except Exception as e:
        print(f"Error testing Prometheus access: {e}")

def test_alertmanager_access():
    """Tests access to Alertmanager."""
    print("\n--- Testing Alertmanager Access ---")
    try:
        url = "http://alertmanager.apps.sddc.info"
        response = requests.get(url)
        if response.status_code == 200:
            print("Alertmanager access successful.")
        else:
            print(f"Alertmanager access failed. Status code: {response.status_code}")
    except Exception as e:
        print(f"Error testing Alertmanager access: {e}")

def main():
    """Main function to verify Kubernetes cluster health."""
    parser = argparse.ArgumentParser(description="Verify Kubernetes cluster health.")
    parser.add_argument("--kubeconfig", help="Path to the kubeconfig file.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output.")
    parser.add_argument("--test-logins", action="store_true", help="Test logins to applications.")
    args = parser.parse_args()

    try:
        if args.kubeconfig:
            config.load_kube_config(config_file=args.kubeconfig)
        else:
            config.load_kube_config()
    except Exception as e:
        print(f"Error loading Kubernetes configuration: {e}")
        return

    print("Starting Kubernetes cluster health verification...")

    unhealthy_nodes, healthy_nodes = check_node_health(args.verbose)
    if unhealthy_nodes is not None:
        if not unhealthy_nodes:
            print("\nNode Health: All nodes are healthy.")
        else:
            print(f"\nNode Health: Found {len(unhealthy_nodes)} unhealthy nodes:")
            for node, reason, message in unhealthy_nodes:
                print(f"  - Node: {node}, Reason: {reason}, Message: {message}")

    unhealthy_pods, healthy_pods = check_pod_health(args.verbose)
    if unhealthy_pods is not None:
        if not unhealthy_pods:
            print("\nPod Health: All pods are healthy.")
        else:
            print(f"\nPod Health: Found {len(unhealthy_pods)} unhealthy pods:")
            for namespace, name, status, reason, message in unhealthy_pods:
                print(f"  - Namespace: {namespace}, Pod: {name}, Status: {status}, Reason: {reason}, Message: {message}")

    if args.test_logins:
        test_argocd_login()
        test_grafana_login()
        test_prometheus_access()
        test_alertmanager_access()

    print("\nCluster health verification finished.")

if __name__ == "__main__":
    main()
