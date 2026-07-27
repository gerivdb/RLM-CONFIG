#!/usr/bin/env python3
"""
RLM-CONFIG - Configuration Drift Guardian
Main entry point
"""

import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.api import create_app, run_scan_all, run_detect

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="RLM-CONFIG - Configuration Drift Guardian (port 8794)")
    parser.add_argument("--port", type=int, default=8794, help="Port to run server on")
    parser.add_argument("--scan", action="store_true", help="Run full scan and exit")
    parser.add_argument("--detect", type=str, help="Run detection on specific repo")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    
    args = parser.parse_args()
    
    # Change to RLM-CONFIG directory
    os.chdir(Path(__file__).parent)
    
    if args.scan:
        run_scan_all()
    elif args.detect:
        run_detect(args.detect)
    else:
        print(f"Starting RLM-CONFIG on {args.host}:{args.port}")
        app = create_app()
        app.run(host=args.host, port=args.port, threaded=True)

if __name__ == "__main__":
    main()