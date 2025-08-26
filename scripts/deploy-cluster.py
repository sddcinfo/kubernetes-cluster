#!/usr/bin/env python3
"""
Main Orchestrator for Kubernetes on Proxmox Deployment
Coordinates all phases of cluster deployment with error handling and state tracking
"""

import os
import sys
import json
import time
import subprocess
import argparse
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from enum import Enum

class Phase(Enum):
    VALIDATE = "01-validate-environment.py"
    BUILD_IMAGE = "02-build-golden-image.sh"
    PROVISION = "03-provision-infrastructure.sh"
    BOOTSTRAP = "04-bootstrap-kubernetes.sh"
    SERVICES = "05-deploy-platform-services.sh"

class DeploymentState:
    """Track deployment state across phases"""
    
    STATE_FILE = "deployment-state.json"
    
    def __init__(self):
        self.state = self.load_state()
    
    def load_state(self) -> Dict:
        """Load state from file if exists"""
        if os.path.exists(self.STATE_FILE):
            with open(self.STATE_FILE, 'r') as f:
                return json.load(f)
        return {
            "phases_completed": [],
            "current_phase": None,
            "start_time": None,
            "end_time": None,
            "status": "not_started"
        }
    
    def save_state(self):
        """Save current state to file"""
        with open(self.STATE_FILE, 'w') as f:
            json.dump(self.state, f, indent=2)
    
    def mark_phase_complete(self, phase: Phase):
        """Mark a phase as completed"""
        phase_name = phase.name
        if phase_name not in self.state["phases_completed"]:
            self.state["phases_completed"].append(phase_name)
        self.state["current_phase"] = None
        self.save_state()
    
    def set_current_phase(self, phase: Phase):
        """Set the current running phase"""
        self.state["current_phase"] = phase.name
        if not self.state["start_time"]:
            self.state["start_time"] = datetime.now().isoformat()
        self.state["status"] = "in_progress"
        self.save_state()
    
    def is_phase_complete(self, phase: Phase) -> bool:
        """Check if a phase is already complete"""
        return phase.name in self.state["phases_completed"]
    
    def mark_complete(self):
        """Mark entire deployment as complete"""
        self.state["status"] = "completed"
        self.state["end_time"] = datetime.now().isoformat()
        self.save_state()
    
    def mark_failed(self, error: str):
        """Mark deployment as failed"""
        self.state["status"] = "failed"
        self.state["error"] = error
        self.state["end_time"] = datetime.now().isoformat()
        self.save_state()
    
    def reset(self):
        """Reset deployment state"""
        self.state = {
            "phases_completed": [],
            "current_phase": None,
            "start_time": None,
            "end_time": None,
            "status": "not_started"
        }
        self.save_state()

class ClusterDeployer:
    """Main orchestrator for cluster deployment"""
    
    def __init__(self, skip_phases: List[str] = None, force_rebuild: bool = False):
        self.state = DeploymentState()
        self.skip_phases = skip_phases or []
        self.force_rebuild = force_rebuild
        
        if force_rebuild:
            self.state.reset()
    
    def run_phase(self, phase: Phase) -> bool:
        """Execute a deployment phase"""
        if phase.name in self.skip_phases:
            print(f"⏭️  Skipping phase: {phase.name}")
            return True
        
        if self.state.is_phase_complete(phase) and not self.force_rebuild:
            print(f"✓ Phase already complete: {phase.name}")
            return True
        
        print(f"\n{'=' * 60}")
        print(f"Starting Phase: {phase.name}")
        print(f"{'=' * 60}\n")
        
        self.state.set_current_phase(phase)
        
        script_path = phase.value
        if not os.path.exists(script_path):
            print(f"❌ Script not found: {script_path}")
            return False
        
        # Make script executable
        os.chmod(script_path, 0o755)
        
        # Determine how to run the script
        if script_path.endswith('.py'):
            cmd = ['python3', script_path]
        elif script_path.endswith('.sh'):
            cmd = ['bash', script_path]
        else:
            cmd = ['./' + script_path]
        
        try:
            result = subprocess.run(cmd, check=True)
            self.state.mark_phase_complete(phase)
            print(f"✅ Phase completed: {phase.name}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"❌ Phase failed: {phase.name}")
            print(f"   Error: {e}")
            return False
        except KeyboardInterrupt:
            print(f"\n⚠️  Deployment interrupted during phase: {phase.name}")
            return False
    
    def deploy(self) -> bool:
        """Run the complete deployment process"""
        print("\n" + "=" * 60)
        print("KUBERNETES ON PROXMOX - AUTOMATED DEPLOYMENT")
        print("=" * 60)
        
        start_time = time.time()
        
        # Define deployment phases in order
        phases = [
            Phase.VALIDATE,
            Phase.BUILD_IMAGE,
            Phase.PROVISION,
            Phase.BOOTSTRAP,
            Phase.SERVICES
        ]
        
        # Show deployment plan
        print("\nDeployment Plan:")
        print("================")
        for phase in phases:
            status = "✓ Complete" if self.state.is_phase_complete(phase) else "⏳ Pending"
            skip = " (SKIP)" if phase.name in self.skip_phases else ""
            print(f"  {phase.name}: {status}{skip}")
        
        print("\nStarting deployment...\n")
        
        # Execute each phase
        for phase in phases:
            if not self.run_phase(phase):
                self.state.mark_failed(f"Failed at phase: {phase.name}")
                print(f"\n❌ Deployment failed at phase: {phase.name}")
                return False
            
            # Add delay between phases
            if phase != phases[-1]:
                print("\n⏳ Waiting 10 seconds before next phase...")
                time.sleep(10)
        
        # Mark deployment complete
        self.state.mark_complete()
        
        elapsed_time = time.time() - start_time
        minutes = int(elapsed_time // 60)
        seconds = int(elapsed_time % 60)
        
        print("\n" + "=" * 60)
        print("✅ DEPLOYMENT COMPLETED SUCCESSFULLY!")
        print(f"Total time: {minutes} minutes {seconds} seconds")
        print("=" * 60)
        
        # Print access information
        print("\nCluster Access:")
        print("==============")
        print("export KUBECONFIG=~/.kube/config-k8s-cluster")
        print("kubectl get nodes")
        print("\nFor detailed access information, see the output from Phase 5")
        
        return True
    
    def cleanup(self) -> bool:
        """Clean up all deployed resources"""
        print("\n⚠️  WARNING: This will destroy all cluster resources!")
        response = input("Are you sure? Type 'yes' to confirm: ")
        
        if response.lower() != 'yes':
            print("Cleanup cancelled")
            return False
        
        print("\nCleaning up resources...")
        
        # Destroy Terraform resources
        print("Destroying infrastructure...")
        os.chdir('../terraform')
        subprocess.run(['terraform', 'destroy', '-auto-approve'], check=False)
        os.chdir('../scripts')
        
        # Remove state file
        if os.path.exists(self.STATE_FILE):
            os.remove(self.STATE_FILE)
        
        print("✅ Cleanup complete")
        return True
    
    def status(self):
        """Show deployment status"""
        print("\nDeployment Status")
        print("=================")
        print(f"Status: {self.state.state['status']}")
        print(f"Current Phase: {self.state.state['current_phase'] or 'None'}")
        print(f"Completed Phases: {', '.join(self.state.state['phases_completed']) or 'None'}")
        
        if self.state.state['start_time']:
            print(f"Start Time: {self.state.state['start_time']}")
        if self.state.state['end_time']:
            print(f"End Time: {self.state.state['end_time']}")
        if self.state.state.get('error'):
            print(f"Error: {self.state.state['error']}")

def main():
    parser = argparse.ArgumentParser(description='Deploy Kubernetes cluster on Proxmox')
    parser.add_argument('action', choices=['deploy', 'status', 'cleanup', 'reset'],
                        help='Action to perform')
    parser.add_argument('--skip-phases', nargs='+', 
                        choices=['VALIDATE', 'BUILD_IMAGE', 'PROVISION', 'BOOTSTRAP', 'SERVICES'],
                        help='Phases to skip')
    parser.add_argument('--force-rebuild', action='store_true',
                        help='Force rebuild even if phases are complete')
    
    args = parser.parse_args()
    
    deployer = ClusterDeployer(
        skip_phases=args.skip_phases or [],
        force_rebuild=args.force_rebuild
    )
    
    if args.action == 'deploy':
        success = deployer.deploy()
        sys.exit(0 if success else 1)
    elif args.action == 'status':
        deployer.status()
    elif args.action == 'cleanup':
        deployer.cleanup()
    elif args.action == 'reset':
        deployer.state.reset()
        print("✅ Deployment state reset")

if __name__ == "__main__":
    main()