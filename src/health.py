"""
RLM-CONFIG - Health, Metrics, Vote, and API Endpoints
Standard RLM runner endpoints for integration with the ecosystem.
"""

import os
import sys
import time
import json
import psutil
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from pathlib import Path
from flask import Flask, request, jsonify

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from config_guardian import ConfigGuardian, Drift, ScanResult


app = Flask(__name__)

# Configuration
CONFIG_DIR = os.environ.get("RLM_CONFIG_DIR", "config")
PORT = int(os.environ.get("RLM_CONFIG_PORT", "8794"))
HOST = os.environ.get("RLM_CONFIG_HOST", "0.0.0.0")

# Service metadata
SERVICE_NAME = "RLM-CONFIG"
SERVICE_PORT = PORT
VERSION = "1.0.0"
START_TIME = time.time()

# Initialize guardian
guardian = ConfigGuardian(config_dir=CONFIG_DIR)

# In-memory metrics store
metrics_store = {
    "total_scans": 0,
    "total_drifts_detected": 0,
    "drifts_by_severity": {"critical": 0, "high": 0, "medium": 0, "low": 0},
    "drifts_by_repo": {},
    "scan_durations_ms": [],
    "last_scan_time": None,
    "file_hashes_tracked": 0
}

# Vote store
vote_store = {
    "active": {},
    "completed": {}
}
vote_lock = threading.Lock()

# Background scan thread
scan_thread = None
scan_running = False


@dataclass
class HealthResponse:
    """Health check response."""
    status: str
    service: str
    version: str
    uptime_seconds: float
    timestamp: str
    checks: Dict[str, Any]


@dataclass
class MetricsResponse:
    """Metrics response."""
    service: str
    timestamp: str
    total_scans: int
    total_drifts_detected: int
    drifts_by_severity: Dict[str, int]
    drifts_by_repo: Dict[str, int]
    scan_duration_avg_ms: float
    last_scan_time: Optional[str]
    file_hashes_tracked: int


@dataclass
class VoteResponse:
    """Vote response."""
    proposal_id: str
    proposal_type: str
    description: str
    votes: Dict[str, int]
    consensus: str
    quorum: bool
    details: Dict[str, Any]


def update_metrics(scan_results: Dict[str, List[ScanResult]]):
    """Update metrics from scan results."""
    metrics_store["total_scans"] += 1
    total_duration = 0
    for repo, results in scan_results.items():
        for result in results:
            metrics_store["total_drifts_detected"] += len(result.drifts)
            for drift in result.drifts:
                metrics_store["drifts_by_severity"][drift.severity] = \
                    metrics_store["drifts_by_severity"].get(drift.severity, 0) + 1
                metrics_store["drifts_by_repo"][repo] = \
                    metrics_store["drifts_by_repo"].get(repo, 0) + 1
            if result.duration_ms > 0:
                metrics_store["scan_durations_ms"].append(result.duration_ms)
                total_duration += result.duration_ms
    metrics_store["last_scan_time"] = datetime.utcnow().isoformat() + "Z"
    metrics_store["file_hashes_tracked"] = len(guardian.checkpoint.get("file_hashes", {}))


def get_avg_scan_duration() -> float:
    """Get average scan duration in milliseconds."""
    durations = metrics_store["scan_durations_ms"]
    if not durations:
        return 0.0
    return sum(durations) / len(durations)


def background_scan():
    """Background periodic scan."""
    global scan_running
    interval = 15 * 60  # 15 minutes
    
    while scan_running:
        try:
            results = guardian.scan_all()
            update_metrics(results)
        except Exception as e:
            pass  # Log in production
        time.sleep(interval)


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint - standard RLM format."""
    # Check dependencies
    checks = {
        "config_dir": {
            "status": "ok" if Path(CONFIG_DIR).exists() else "fail",
            "path": CONFIG_DIR
        },
        "rules_file": {
            "status": "ok" if Path(CONFIG_DIR, "rules.yaml").exists() else "fail",
            "path": str(Path(CONFIG_DIR, "rules.yaml"))
        },
        "targets_file": {
            "status": "ok" if Path(CONFIG_DIR, "scan_targets.yaml").exists() else "fail",
            "path": str(Path(CONFIG_DIR, "scan_targets.yaml"))
        },
        "checkpoint_file": {
            "status": "ok" if Path(CONFIG_DIR, "checkpoint.json").exists() else "warn",
            "path": str(Path(CONFIG_DIR, "checkpoint.json"))
        },
        "memory": {
            "status": "ok",
            "usage_mb": round(psutil.Process().memory_info().rss / 1024 / 1024, 2)
        },
        "disk": {
            "status": "ok",
            "free_gb": round(psutil.disk_usage("/").free / 1024 / 1024 / 1024, 2)
        },
        "background_scan": {
            "status": "running" if scan_running else "stopped"
        }
    }
    
    overall_status = "ok"
    for check in checks.values():
        if check.get("status") == "fail":
            overall_status = "fail"
            break
        elif check.get("status") == "warn" and overall_status == "ok":
            overall_status = "warn"
    
    response = HealthResponse(
        status=overall_status,
        service=SERVICE_NAME,
        version=VERSION,
        uptime_seconds=time.time() - START_TIME,
        timestamp=datetime.utcnow().isoformat() + "Z",
        checks=checks
    )
    return jsonify(asdict(response))


@app.route("/metrics", methods=["GET"])
def metrics():
    """Metrics endpoint - standard RLM format."""
    response = MetricsResponse(
        service=SERVICE_NAME,
        timestamp=datetime.utcnow().isoformat() + "Z",
        total_scans=metrics_store["total_scans"],
        total_drifts_detected=metrics_store["total_drifts_detected"],
        drifts_by_severity=metrics_store["drifts_by_severity"],
        drifts_by_repo=metrics_store["drifts_by_repo"],
        scan_duration_avg_ms=round(get_avg_scan_duration(), 2),
        last_scan_time=metrics_store["last_scan_time"],
        file_hashes_tracked=metrics_store["file_hashes_tracked"]
    )
    return jsonify(asdict(response))


@app.route("/vote", methods=["GET"])
def vote_list():
    """List active and completed votes."""
    with vote_lock:
        return jsonify({
            "service": SERVICE_NAME,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "active_votes": list(vote_store["active"].values()),
            "completed_votes": list(vote_store["completed"].values())
        })


@app.route("/vote/<proposal_id>", methods=["GET"])
def vote_get(proposal_id):
    """Get specific vote details."""
    with vote_lock:
        if proposal_id in vote_store["active"]:
            return jsonify(asdict(vote_store["active"][proposal_id]))
        if proposal_id in vote_store["completed"]:
            return jsonify(asdict(vote_store["completed"][proposal_id]))
    return jsonify({"error": "Vote not found"}), 404


@app.route("/vote", methods=["POST"])
def vote_create():
    """Create a new vote proposal."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON body"}), 400
    
    proposal_id = data.get("proposal_id", f"vote-{int(time.time())}")
    proposal_type = data.get("type", "config_fix")
    description = data.get("description", "")
    details = data.get("details", {})
    
    vote = VoteResponse(
        proposal_id=proposal_id,
        proposal_type=proposal_type,
        description=description,
        votes={"C": 0, "E": 0, "Obs": 0},
        consensus="pending",
        quorum=False,
        details=details
    )
    
    with vote_lock:
        vote_store["active"][proposal_id] = vote
    
    return jsonify(asdict(vote)), 201


@app.route("/vote/<proposal_id>/cast", methods=["POST"])
def vote_cast(proposal_id):
    """Cast a vote."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON body"}), 400
    
    voter = data.get("voter", "unknown")  # C, E, or Obs
    choice = data.get("choice")  # approve, reject
    
    if voter not in ["C", "E", "Obs"]:
        return jsonify({"error": "Invalid voter role"}), 400
    if choice not in ["approve", "reject"]:
        return jsonify({"error": "Invalid choice"}), 400
    
    with vote_lock:
        if proposal_id not in vote_store["active"]:
            return jsonify({"error": "Vote not found"}), 404
        
        vote = vote_store["active"][proposal_id]
        vote.votes[voter] = 1 if choice == "approve" else -1
        
        # Check consensus (ternary: at least 2 approve)
        approves = sum(1 for v in vote.votes.values() if v > 0)
        if approves >= 2:
            vote.consensus = "accepted"
            vote.quorum = True
            vote_store["completed"][proposal_id] = vote
            del vote_store["active"][proposal_id]
        elif sum(1 for v in vote.votes.values() if v != 0) == 3:
            # All voted, no quorum
            vote.consensus = "rejected"
            vote.quorum = True
            vote_store["completed"][proposal_id] = vote
            del vote_store["active"][proposal_id]
    
    return jsonify(asdict(vote))


@app.route("/detect", methods=["POST"])
def detect():
    """Scan for configuration drifts."""
    data = request.get_json() or {}
    repo = data.get("repo")
    all_repos = data.get("all", False)
    
    start_time = time.time()
    
    if all_repos:
        results = guardian.scan_all()
    elif repo:
        results = {repo: guardian.scan_repo(repo)}
    else:
        return jsonify({"error": "repo or all=true required"}), 400
    
    duration = (time.time() - start_time) * 1000
    
    # Update metrics
    update_metrics(results)
    
    # Format response
    formatted_results = {}
    summary = {
        "total_repos": len(results),
        "total_drifts": 0,
        "by_severity": {"critical": 0, "high": 0, "medium": 0, "low": 0},
        "auto_fixable": 0
    }
    
    for repo_name, scan_results in results.items():
        formatted_results[repo_name] = []
        for result in scan_results:
            drifts_data = []
            for drift in result.drifts:
                drifts_data.append({
                    "drift_id": drift.drift_id,
                    "severity": drift.severity,
                    "file": drift.target_file,
                    "description": drift.description,
                    "details": drift.details,
                    "auto_fixable": drift.auto_fixable,
                    "fix_action": drift.fix_action,
                    "fix_details": drift.fix_details,
                    "detected_at": drift.detected_at
                })
                summary["total_drifts"] += 1
                summary["by_severity"][drift.severity] += 1
                if drift.auto_fixable:
                    summary["auto_fixable"] += 1
            
            formatted_results[repo_name].append({
                "file": result.file,
                "scanned_at": result.scanned_at,
                "duration_ms": result.duration_ms,
                "drifts": drifts_data
            })
    
    return jsonify({
        "service": SERVICE_NAME,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "scan_duration_ms": round(duration, 2),
        "summary": summary,
        "results": formatted_results
    })


@app.route("/fix", methods=["POST"])
def fix():
    """Apply auto-fixes for detected drifts."""
    data = request.get_json() or {}
    repo = data.get("repo")
    drift_ids = data.get("drifts", [])  # List of drift_ids to fix
    dry_run = data.get("dry_run", True)
    
    if not repo:
        return jsonify({"error": "repo required"}), 400
    
    # First scan to get current drifts
    results = guardian.scan_repo(repo)
    all_drifts = []
    for result in results:
        all_drifts.extend(result.drifts)
    
    # Filter to requested drifts or all auto-fixable
    if drift_ids:
        target_drifts = [d for d in all_drifts if d.drift_id in drift_ids]
    else:
        target_drifts = [d for d in all_drifts if d.auto_fixable]
    
    fix_results = []
    for drift in target_drifts:
        fix_result = guardian.apply_fix(drift, dry_run=dry_run)
        fix_results.append({
            "drift_id": drift.drift_id,
            "file": drift.target_file,
            "success": fix_result["success"],
            "dry_run": fix_result["dry_run"],
            "action": fix_result["action"],
            "details": fix_result["details"],
            "error": fix_result.get("error")
        })
    
    return jsonify({
        "service": SERVICE_NAME,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "repo": repo,
        "dry_run": dry_run,
        "fixes": fix_results,
        "summary": {
            "attempted": len(fix_results),
            "successful": sum(1 for r in fix_results if r["success"]),
            "failed": sum(1 for r in fix_results if not r["success"])
        }
    })


@app.route("/audit/<path:file_path>", methods=["GET"])
def audit(file_path):
    """Get audit history for a configuration file."""
    # Check if file is in checkpoint
    file_key = None
    for key in guardian.checkpoint.get("file_hashes", {}):
        if file_path in key or key.endswith(file_path):
            file_key = key
            break
    
    if not file_key:
        return jsonify({"error": "File not tracked"}), 404
    
    # Return checkpoint history (simplified)
    return jsonify({
        "service": SERVICE_NAME,
        "file": file_path,
        "tracked_since": "unknown",  # Would need history tracking
        "current_hash": guardian.checkpoint["file_hashes"][file_key],
        "last_scan": guardian.checkpoint.get("last_scan"),
        "history": []  # Would need extended checkpoint
    })


@app.route("/scan/start", methods=["POST"])
def scan_start():
    """Start background periodic scanning."""
    global scan_thread, scan_running
    
    if scan_running:
        return jsonify({"status": "already_running"}), 200
    
    scan_running = True
    scan_thread = threading.Thread(target=background_scan, daemon=True)
    scan_thread.start()
    
    return jsonify({
        "status": "started",
        "interval_minutes": 15,
        "service": SERVICE_NAME
    })


@app.route("/scan/stop", methods=["POST"])
def scan_stop():
    """Stop background periodic scanning."""
    global scan_running
    
    scan_running = False
    
    return jsonify({
        "status": "stopped",
        "service": SERVICE_NAME
    })


@app.route("/scan/trigger", methods=["POST"])
def scan_trigger():
    """Trigger an immediate scan."""
    data = request.get_json() or {}
    repo = data.get("repo")
    all_repos = data.get("all", False)
    
    if all_repos:
        results = guardian.scan_all()
    elif repo:
        results = {repo: guardian.scan_repo(repo)}
    else:
        return jsonify({"error": "repo or all=true required"}), 400
    
    update_metrics(results)
    
    return jsonify({
        "status": "completed",
        "service": SERVICE_NAME,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "results": {k: len(v) for k, v in results.items()}
    })


def main():
    """Main entry point."""
    # Start background scan by default
    global scan_running, scan_thread
    scan_running = True
    scan_thread = threading.Thread(target=background_scan, daemon=True)
    scan_thread.start()
    
    print(f"Starting {SERVICE_NAME} v{VERSION} on {HOST}:{PORT}")
    print(f"Config dir: {CONFIG_DIR}")
    print(f"Endpoints:")
    print(f"  GET  /health")
    print(f"  GET  /metrics")
    print(f"  GET  /vote")
    print(f"  POST /vote")
    print(f"  POST /detect")
    print(f"  POST /fix")
    print(f"  GET  /audit/<file>")
    print(f"  POST /scan/start")
    print(f"  POST /scan/stop")
    print(f"  POST /scan/trigger")
    
    app.run(host=HOST, port=PORT, debug=False)


if __name__ == "__main__":
    main()