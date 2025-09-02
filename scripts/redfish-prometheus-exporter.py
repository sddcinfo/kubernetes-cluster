#!/usr/bin/env python3
"""
Redfish Prometheus Exporter for Hardware Sensor Monitoring
Collects temperature and fan data from multiple Redfish-enabled nodes
"""

import json
import os
import sys
import time
import subprocess
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import threading
import signal


class RedfishCollector:
    def __init__(self, redfish_script_path, nodes=None):
        self.redfish_script = redfish_script_path
        self.nodes = nodes or ["console-node1", "console-node2", "console-node3", "console-node4"]
        self.last_collection_time = 0
        self.cached_metrics = ""
        self.collection_interval = 30  # seconds
        
    def collect_sensor_data(self, node):
        """Collect sensor data from a specific node"""
        try:
            cmd = [sys.executable, self.redfish_script, node, "sensors", "--json"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                return json.loads(result.stdout)
            else:
                print(f"Error collecting data from {node}: {result.stderr}", file=sys.stderr)
                return None
                
        except subprocess.TimeoutExpired:
            print(f"Timeout collecting data from {node}", file=sys.stderr)
            return None
        except json.JSONDecodeError as e:
            print(f"JSON decode error for {node}: {e}", file=sys.stderr)
            return None
        except Exception as e:
            print(f"Unexpected error collecting data from {node}: {e}", file=sys.stderr)
            return None

    def format_prometheus_metrics(self, sensor_data, node):
        """Convert sensor data to Prometheus format"""
        metrics = []
        
        if not sensor_data:
            return ""
            
        # Temperature metrics
        if "Temperatures" in sensor_data:
            for temp in sensor_data["Temperatures"]:
                labels = {
                    'node': node,
                    'sensor_name': temp.get('Name', 'Unknown'),
                    'sensor_id': temp.get('MemberId', ''),
                    'physical_context': temp.get('PhysicalContext', 'Unknown').lower(),
                    'health_status': temp.get('Status', {}).get('Health', 'Unknown')
                }
                
                # Temperature reading
                if 'ReadingCelsius' in temp:
                    label_str = ','.join([f'{k}="{v}"' for k, v in labels.items()])
                    metrics.append(f'redfish_temperature_celsius{{{label_str}}} {temp["ReadingCelsius"]}')
                
                # Temperature thresholds
                for threshold_type, metric_suffix in [
                    ('UpperThresholdCritical', 'upper_critical'),
                    ('UpperThresholdNonCritical', 'upper_warning'),
                    ('LowerThresholdCritical', 'lower_critical'),
                    ('LowerThresholdNonCritical', 'lower_warning')
                ]:
                    if threshold_type in temp:
                        threshold_labels = labels.copy()
                        threshold_labels['threshold_type'] = metric_suffix
                        threshold_label_str = ','.join([f'{k}="{v}"' for k, v in threshold_labels.items()])
                        metrics.append(f'redfish_temperature_threshold_celsius{{{threshold_label_str}}} {temp[threshold_type]}')

        # Fan metrics
        if "Fans" in sensor_data:
            for fan in sensor_data["Fans"]:
                labels = {
                    'node': node,
                    'fan_name': fan.get('Name', 'Unknown'),
                    'fan_id': fan.get('MemberId', ''),
                    'health_status': fan.get('Status', {}).get('Health', 'Unknown')
                }
                
                # Fan speed reading
                if 'Reading' in fan:
                    label_str = ','.join([f'{k}="{v}"' for k, v in labels.items()])
                    metrics.append(f'redfish_fan_speed_rpm{{{label_str}}} {fan["Reading"]}')
                
                # Fan thresholds
                for threshold_type, metric_suffix in [
                    ('UpperThresholdCritical', 'upper_critical'),
                    ('UpperThresholdNonCritical', 'upper_warning'),
                    ('LowerThresholdCritical', 'lower_critical'),
                    ('LowerThresholdNonCritical', 'lower_warning')
                ]:
                    if threshold_type in fan:
                        threshold_labels = labels.copy()
                        threshold_labels['threshold_type'] = metric_suffix
                        threshold_label_str = ','.join([f'{k}="{v}"' for k, v in threshold_labels.items()])
                        metrics.append(f'redfish_fan_threshold_rpm{{{threshold_label_str}}} {fan[threshold_type]}')

        return '\n'.join(metrics)

    def collect_all_metrics(self):
        """Collect metrics from all nodes"""
        all_metrics = []
        
        # Add metadata
        all_metrics.append('# HELP redfish_temperature_celsius Temperature reading in Celsius')
        all_metrics.append('# TYPE redfish_temperature_celsius gauge')
        all_metrics.append('# HELP redfish_temperature_threshold_celsius Temperature threshold values')
        all_metrics.append('# TYPE redfish_temperature_threshold_celsius gauge')
        all_metrics.append('# HELP redfish_fan_speed_rpm Fan speed in RPM')
        all_metrics.append('# TYPE redfish_fan_speed_rpm gauge')
        all_metrics.append('# HELP redfish_fan_threshold_rpm Fan speed threshold values')
        all_metrics.append('# TYPE redfish_fan_threshold_rpm gauge')
        all_metrics.append('')

        for node in self.nodes:
            print(f"Collecting metrics from {node}...")
            sensor_data = self.collect_sensor_data(node)
            
            if sensor_data:
                node_metrics = self.format_prometheus_metrics(sensor_data, node)
                if node_metrics:
                    all_metrics.append(f'# Node: {node}')
                    all_metrics.append(node_metrics)
                    all_metrics.append('')
                    
        # Add collection timestamp
        all_metrics.append(f'redfish_collection_timestamp {int(time.time())}')
        
        return '\n'.join(all_metrics)

    def get_metrics(self):
        """Get cached or fresh metrics based on collection interval"""
        current_time = time.time()
        
        if current_time - self.last_collection_time > self.collection_interval:
            print("Collecting fresh metrics...")
            self.cached_metrics = self.collect_all_metrics()
            self.last_collection_time = current_time
            
        return self.cached_metrics


class MetricsHandler(BaseHTTPRequestHandler):
    def __init__(self, collector, *args, **kwargs):
        self.collector = collector
        super().__init__(*args, **kwargs)
    
    def do_GET(self):
        if self.path == '/metrics':
            metrics = self.collector.get_metrics()
            
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(metrics.encode('utf-8'))
        elif self.path == '/health' or self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Redfish Exporter is running')
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        # Suppress default HTTP log messages
        pass


def create_handler(collector):
    def handler(*args, **kwargs):
        return MetricsHandler(collector, *args, **kwargs)
    return handler


def main():
    parser = argparse.ArgumentParser(description='Redfish Prometheus Exporter')
    parser.add_argument('--port', type=int, default=9101, help='Port to listen on (default: 9101)')
    parser.add_argument('--redfish-script', default='/home/sysadmin/claude/ansible-provisioning-server/redfish.py',
                       help='Path to redfish.py script')
    parser.add_argument('--nodes', nargs='+', 
                       default=['console-node1', 'console-node2', 'console-node3', 'console-node4'],
                       help='List of nodes to monitor')
    parser.add_argument('--interval', type=int, default=30, help='Collection interval in seconds (default: 30)')
    
    args = parser.parse_args()
    
    # Validate redfish script exists
    if not os.path.exists(args.redfish_script):
        print(f"Error: Redfish script not found at {args.redfish_script}")
        sys.exit(1)
    
    # Create collector
    collector = RedfishCollector(args.redfish_script, args.nodes)
    collector.collection_interval = args.interval
    
    # Create HTTP server
    handler = create_handler(collector)
    server = HTTPServer(('0.0.0.0', args.port), handler)
    
    print(f"Starting Redfish Prometheus Exporter on port {args.port}")
    print(f"Monitoring nodes: {', '.join(args.nodes)}")
    print(f"Collection interval: {args.interval} seconds")
    print(f"Metrics endpoint: http://localhost:{args.port}/metrics")
    
    def signal_handler(signum, frame):
        print("\nShutting down exporter...")
        server.shutdown()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down exporter...")
        server.shutdown()


if __name__ == '__main__':
    main()