"""
RLM-CONFIG - Main API Entry Point
"""

import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from health import app
from config_guardian import ConfigGuardian

def create_app():
    """Create and configure the Flask app."""
    return app

def run_scan_all():
    """Run a full scan of all repositories."""
    guardian = ConfigGuardian(config_dir="config")
    results = guardian.scan_all()
    
    print(f"\n{'='*60}")
    print(f"RLM-CONFIG Full Scan Results")
    print(f"{'='*60}")
    
    total_drifts = 0
    for repo, scan_results in results.items():
        repo_drifts = sum(len(r.drifts) for r in scan_results)
        total_drifts += repo_drifts
        if repo_drifts > 0:
            print(f"\n[DIR] {repo}: {repo_drifts} drift(s)")
            for result in scan_results:
                for drift in result.drifts:
                    print(f"  * [{drift.severity.upper()}] {drift.drift_id}: {drift.description}")
                    if drift.details:
                        for k, v in drift.details.items():
                            print(f"      {k}: {v}")
        else:
            print(f"\n[OK] {repo}: No drifts detected")
    
    print(f"\n{'='*60}")
    print(f"Total: {total_drifts} drift(s) across {len(results)} repo(s)")
    print(f"{'='*60}\n")
    
    return results

def run_detect(repo: str = None):
    """Run detection on specific repo or all."""
    guardian = ConfigGuardian(config_dir="config")
    if repo:
        results = {repo: guardian.scan_repo(repo)}
    else:
        results = guardian.scan_all()
    
    return results

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="RLM-CONFIG - Configuration Drift Guardian")
    parser.add_argument("--port", type=int, default=8794, help="Port to run server on")
    parser.add_argument("--scan", action="store_true", help="Run full scan and exit")
    parser.add_argument("--detect", type=str, help="Run detection on specific repo")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    
    args = parser.parse_args()
    
    if args.scan:
        run_scan_all()
    elif args.detect:
        run_detect(args.detect)
    else:
        print(f"Starting RLM-CONFIG on {args.host}:{args.port}")
        app.run(host=args.host, port=args.port, threaded=True)