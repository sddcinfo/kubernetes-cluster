#!/home/sysadmin/claude/kubernetes-cluster/kubespray/venv/bin/python

import argparse
import os
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

def main():
    """Main function to verify Kubernetes cluster health."""
    parser = argparse.ArgumentParser(description="Verify Kubernetes cluster health.")
    parser.add_argument("--kubeconfig", help="Path to the kubeconfig file.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output.")
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

    print("\nCluster health verification finished.")

if __name__ == "__main__":
    main()