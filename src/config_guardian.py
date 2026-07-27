"""
RLM-CONFIG - Configuration Drift Guardian
Core detection and correction engine for configuration files.
"""

import yaml
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib


def _remove_duplicate_yaml_anchors(content: str) -> str:
    """Remove duplicate YAML anchor definitions from content (keep first occurrence).
    
    This handles the specific case in known_repositories.yaml where the same
    anchor (&id002, &id003, etc.) is defined multiple times for enforcement_mode.
    
    For anchors on complex values (followed by indented content), we still remove
    the duplicate anchor but keep the content inlined.
    """
    lines = content.split('\n')
    seen_anchors = set()
    result_lines = []
    
    for i, line in enumerate(lines):
        # Match anchor definition at end of line: key: &anchor_name [# comment]
        match = re.match(r'^(\s*\w+:\s*)&(\w+)(\s*#.*)?$', line)
        
        if match:
            key_part = match.group(1)      # "key: "
            anchor_name = match.group(2)
            comment = match.group(3) or ''
            
            if anchor_name in seen_anchors:
                # Duplicate anchor - remove the anchor but keep the key and comment
                # This works for both scalar values and complex values (content gets inlined)
                line = f'{key_part}{comment}'
            else:
                seen_anchors.add(anchor_name)
        
        result_lines.append(line)
    
    return '\n'.join(result_lines)


@dataclass
class Drift:
    """Represents a configuration drift."""
    drift_id: str
    severity: str  # critical, high, medium, low
    target_file: str
    repo: str
    description: str
    details: Dict[str, Any] = field(default_factory=dict)
    auto_fixable: bool = False
    fix_action: Optional[str] = None
    fix_details: Dict[str, Any] = field(default_factory=dict)
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ScanResult:
    """Result of a configuration scan."""
    repo: str
    file: str
    drifts: List[Drift]
    scanned_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    duration_ms: float = 0.0


class ConfigGuardian:
    """Core engine for detecting and fixing configuration drifts."""

    def __init__(self, config_dir: str = "config"):
        self.config_dir = Path(config_dir)
        self.rules = self._load_rules()
        self.targets = self._load_targets()
        self.checkpoint_file = self.config_dir / "checkpoint.json"
        self.checkpoint = self._load_checkpoint()

    def _load_rules(self) -> Dict[str, Any]:
        """Load detection rules from rules.yaml."""
        rules_path = self.config_dir / "rules.yaml"
        with open(rules_path, 'r', encoding='utf-8') as f:
            content = _remove_duplicate_yaml_anchors(f.read())
            return yaml.safe_load(content)

    def _load_targets(self) -> Dict[str, Any]:
        """Load scan targets from scan_targets.yaml."""
        targets_path = self.config_dir / "scan_targets.yaml"
        with open(targets_path, 'r', encoding='utf-8') as f:
            content = _remove_duplicate_yaml_anchors(f.read())
            return yaml.safe_load(content)

    def _load_checkpoint(self) -> Dict[str, Any]:
        """Load checkpoint state."""
        if self.checkpoint_file.exists():
            with open(self.checkpoint_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"history": [], "last_scan": None}

    def _save_checkpoint(self):
        """Save checkpoint state."""
        with open(self.checkpoint_file, 'w', encoding='utf-8') as f:
            json.dump(self.checkpoint, f, indent=2)

    def _compute_hash(self, content: str) -> str:
        """Compute SHA256 hash of content."""
        return hashlib.sha256(content.encode()).hexdigest()

    def scan_repo(self, repo_name: str) -> List[ScanResult]:
        """Scan a specific repository for configuration drifts."""
        target = next((t for t in self.targets["targets"] if t["repo"] == repo_name), None)
        if not target:
            return []

        results = []
        ruleset_name = target.get("ruleset", "default")
        ruleset = self.targets.get("rulesets", {}).get(ruleset_name, [])

        for file_spec in target.get("files", []):
            file_path = Path(target["local_path"]) / file_spec
            if not file_path.exists():
                # Create a drift for missing file
                drift = Drift(
                    drift_id="DRIFT_FILE_MISSING",
                    severity="critical",
                    target_file=file_spec,
                    repo=repo_name,
                    description=f"Configuration file {file_spec} not found at {file_path}",
                    details={"expected_path": str(file_path)},
                    auto_fixable=False
                )
                results.append(ScanResult(
                    repo=repo_name,
                    file=file_spec,
                    drifts=[drift]
                ))
                continue

            # Read file content
            content = file_path.read_text(encoding='utf-8')
            file_hash = self._compute_hash(content)

            # Check if file changed since last scan
            last_hash = self.checkpoint.get("file_hashes", {}).get(str(file_path))
            if last_hash == file_hash:
                # No changes, skip detailed scan
                results.append(ScanResult(
                    repo=repo_name,
                    file=file_spec,
                    drifts=[]
                ))
                continue

            drifts = []
            # Parse file based on extension
            if file_path.suffix in ['.yaml', '.yml']:
                content = _remove_duplicate_yaml_anchors(content)
                try:
                    parsed = yaml.safe_load(content)
                except Exception as exc:
                    if "file_hashes" not in self.checkpoint:
                        self.checkpoint["file_hashes"] = {}
                    self.checkpoint["file_hashes"][str(file_path)] = file_hash
                    drifts.append(Drift(
                        drift_id="YAML_PARSE_ERROR",
                        severity="critical",
                        target_file=file_spec,
                        repo=repo_name,
                        description=f"YAML parse error: {exc}",
                        details={"error": str(exc), "parser": "yaml.safe_load"},
                        auto_fixable=False,
                        fix_action="Fix YAML syntax in source repository"
                    ))
                    results.append(ScanResult(
                        repo=repo_name,
                        file=file_spec,
                        drifts=drifts
                    ))
                    continue
            elif file_path.suffix == '.json':
                try:
                    parsed = json.loads(content)
                except Exception as exc:
                    if "file_hashes" not in self.checkpoint:
                        self.checkpoint["file_hashes"] = {}
                    self.checkpoint["file_hashes"][str(file_path)] = file_hash
                    results.append(ScanResult(
                        repo=repo_name,
                        file=file_spec,
                        drifts=[Drift(
                            drift_id="JSON_PARSE_ERROR",
                            severity="critical",
                            target_file=file_spec,
                            repo=repo_name,
                            description=f"JSON parse error: {exc}",
                            details={"error": str(exc), "parser": "json.loads"},
                            auto_fixable=False,
                            fix_action="Fix JSON syntax in source repository"
                        )]
                    ))
                    continue
            else:
                parsed = {"raw": content}

            # Run detection rules
            drifts = self._run_detection_rules(
                repo_name, file_spec, parsed, ruleset, content
            )

            # Update checkpoint
            if "file_hashes" not in self.checkpoint:
                self.checkpoint["file_hashes"] = {}
            self.checkpoint["file_hashes"][str(file_path)] = file_hash

            results.append(ScanResult(
                repo=repo_name,
                file=file_spec,
                drifts=drifts
            ))

        return results

    def _run_detection_rules(
        self,
        repo: str,
        file: str,
        parsed: Any,
        ruleset: List[str],
        raw_content: str
    ) -> List[Drift]:
        """Run detection rules against parsed configuration."""
        drifts = []
        schemas = self.rules.get("schemas", {})
        detection_rules = self.rules.get("detection_rules", [])

        for rule in detection_rules:
            if rule["id"] not in ruleset:
                continue

            if rule["target"] != file and rule["target"] != "all":
                continue

            check_method = getattr(self, f"_check_{rule['check']}", None)
            if not check_method:
                continue

            try:
                rule_drifts = check_method(repo, file, parsed, rule, schemas)
                drifts.extend(rule_drifts)
            except Exception as e:
                # Log error but continue
                pass

        return drifts

    def _check_required_fields_present(
        self,
        repo: str,
        file: str,
        parsed: Any,
        rule: Dict,
        schemas: Dict
    ) -> List[Drift]:
        """Check that all required fields are present."""
        drifts = []
        schema = schemas.get("known_repositories", {})
        required = schema.get("required_fields", [])

        if isinstance(parsed, dict) and "P0_REPOS" in parsed:
            for section in ["P0_REPOS", "P1_REPOS", "P2_REPOS", "P3_REPOS", "P4_REPOS", "P5_REPOS"]:
                if section in parsed:
                    for idx, entry in enumerate(parsed[section]):
                        if not isinstance(entry, dict):
                            continue
                        for field in required:
                            if field not in entry:
                                drifts.append(Drift(
                                    drift_id=rule["id"],
                                    severity=rule["severity"],
                                    target_file=file,
                                    repo=repo,
                                    description=f"Missing required field '{field}' in {section}[{idx}] ({entry.get('name', 'unknown')})",
                                    details={
                                        "section": section,
                                        "index": idx,
                                        "missing_field": field,
                                        "entry_name": entry.get('name', 'unknown')
                                    },
                                    auto_fixable=rule["id"] in [r["drift_id"] for r in self.rules.get("auto_fix_rules", [])]
                                ))
        return drifts

    def _check_valid_layer(
        self,
        repo: str,
        file: str,
        parsed: Any,
        rule: Dict,
        schemas: Dict
    ) -> List[Drift]:
        """Check that layer values are valid."""
        drifts = []
        schema = schemas.get("known_repositories", {})
        valid_layers = schema.get("valid_layers", [])

        if isinstance(parsed, dict):
            for section in ["P0_REPOS", "P1_REPOS", "P2_REPOS", "P3_REPOS", "P4_REPOS", "P5_REPOS"]:
                if section in parsed:
                    for idx, entry in enumerate(parsed[section]):
                        if not isinstance(entry, dict):
                            continue
                        layer = entry.get("layer")
                        if layer and layer not in valid_layers:
                            drifts.append(Drift(
                                drift_id=rule["id"],
                                severity=rule["severity"],
                                target_file=file,
                                repo=repo,
                                description=f"Invalid layer '{layer}' in {section}[{idx}] ({entry.get('name', 'unknown')})",
                                details={
                                    "section": section,
                                    "index": idx,
                                    "invalid_layer": layer,
                                    "valid_layers": valid_layers,
                                    "entry_name": entry.get('name', 'unknown')
                                },
                                auto_fixable=False
                            ))
        return drifts

    def _check_valid_status(
        self,
        repo: str,
        file: str,
        parsed: Any,
        rule: Dict,
        schemas: Dict
    ) -> List[Drift]:
        """Check that status values are valid."""
        drifts = []
        schema = schemas.get("known_repositories", {})
        valid_statuses = schema.get("valid_statuses", [])

        if isinstance(parsed, dict):
            for section in ["P0_REPOS", "P1_REPOS", "P2_REPOS", "P3_REPOS", "P4_REPOS", "P5_REPOS"]:
                if section in parsed:
                    for idx, entry in enumerate(parsed[section]):
                        if not isinstance(entry, dict):
                            continue
                        status = entry.get("status")
                        if status and status not in valid_statuses:
                            drifts.append(Drift(
                                drift_id=rule["id"],
                                severity=rule["severity"],
                                target_file=file,
                                repo=repo,
                                description=f"Invalid status '{status}' in {section}[{idx}] ({entry.get('name', 'unknown')})",
                                details={
                                    "section": section,
                                    "index": idx,
                                    "invalid_status": status,
                                    "valid_statuses": valid_statuses,
                                    "entry_name": entry.get('name', 'unknown')
                                },
                                auto_fixable=True,
                                fix_action="set_default",
                                fix_details={"default_value": "active"}
                            ))
        return drifts

    def _check_local_path_present_if_active(
        self,
        repo: str,
        file: str,
        parsed: Any,
        rule: Dict,
        schemas: Dict
    ) -> List[Drift]:
        """Check that active repos have local_path defined."""
        drifts = []

        if isinstance(parsed, dict):
            for section in ["P0_REPOS", "P1_REPOS", "P2_REPOS", "P3_REPOS", "P4_REPOS", "P5_REPOS"]:
                if section in parsed:
                    for idx, entry in enumerate(parsed[section]):
                        if not isinstance(entry, dict):
                            continue
                        status = entry.get("status", "").lower()
                        if status in ["active", "actif"]:
                            local_path = entry.get("local_path")
                            if not local_path or local_path == "null":
                                drifts.append(Drift(
                                    drift_id=rule["id"],
                                    severity=rule["severity"],
                                    target_file=file,
                                    repo=repo,
                                    description=f"Active repo missing local_path in {section}[{idx}] ({entry.get('name', 'unknown')})",
                                    details={
                                        "section": section,
                                        "index": idx,
                                        "entry_name": entry.get('name', 'unknown'),
                                        "status": status
                                    },
                                    auto_fixable=True,
                                    fix_action="infer_path",
                                    fix_details={"layer": entry.get("layer"), "name": entry.get("name")}
                                ))
        return drifts

    def _check_repo_entries_complete(
        self,
        repo: str,
        file: str,
        parsed: Any,
        rule: Dict,
        schemas: Dict
    ) -> List[Drift]:
        """Check ECOS_ROOT.json has all known repos."""
        # This would compare with known_repositories.yaml
        # For now, basic structure validation
        drifts = []
        if isinstance(parsed, dict):
            if "repos" not in parsed:
                drifts.append(Drift(
                    drift_id=rule["id"],
                    severity=rule["severity"],
                    target_file=file,
                    repo=repo,
                    description="ECOS_ROOT.json missing 'repos' array",
                    details={},
                    auto_fixable=False
                ))
        return drifts

    def _check_mcp_server_fields(
        self,
        repo: str,
        file: str,
        parsed: Any,
        rule: Dict,
        schemas: Dict
    ) -> List[Drift]:
        """Check MCP server has required fields."""
        drifts = []
        schema = schemas.get("kilocode_mcp", {})
        server_required = schema.get("server_required_fields", [])

        if isinstance(parsed, dict) and "mcpServers" in parsed:
            for server_name, server_config in parsed["mcpServers"].items():
                for field in server_required:
                    if field not in server_config:
                        drifts.append(Drift(
                            drift_id=rule["id"],
                            severity=rule["severity"],
                            target_file=file,
                            repo=repo,
                            description=f"MCP server '{server_name}' missing required field '{field}'",
                            details={
                                "server": server_name,
                                "missing_field": field
                            },
                            auto_fixable=False
                        ))
        return drifts

    def _check_do_not_create_present(
        self,
        repo: str,
        file: str,
        parsed: Any,
        rule: Dict,
        schemas: Dict
    ) -> List[Drift]:
        """Check do_not_create flag is present."""
        drifts = []

        if isinstance(parsed, dict):
            for section in ["P0_REPOS", "P1_REPOS", "P2_REPOS", "P3_REPOS", "P4_REPOS", "P5_REPOS"]:
                if section in parsed:
                    for idx, entry in enumerate(parsed[section]):
                        if not isinstance(entry, dict):
                            continue
                        if "do_not_create" not in entry:
                            drifts.append(Drift(
                                drift_id=rule["id"],
                                severity=rule["severity"],
                                target_file=file,
                                repo=repo,
                                description=f"Missing do_not_create flag in {section}[{idx}] ({entry.get('name', 'unknown')})",
                                details={
                                    "section": section,
                                    "index": idx,
                                    "entry_name": entry.get('name', 'unknown')
                                },
                                auto_fixable=True,
                                fix_action="add_field",
                                fix_details={"default_value": True}
                            ))
        return drifts

    def _check_enforcement_mode_complete(
        self,
        repo: str,
        file: str,
        parsed: Any,
        rule: Dict,
        schemas: Dict
    ) -> List[Drift]:
        """Check enforcement_mode has all required keys."""
        drifts = []
        schema = schemas.get("known_repositories", {})
        required_keys = schema.get("valid_enforcement_modes", [])

        if isinstance(parsed, dict):
            for section in ["P0_REPOS", "P1_REPOS", "P2_REPOS", "P3_REPOS", "P4_REPOS", "P5_REPOS"]:
                if section in parsed:
                    for idx, entry in enumerate(parsed[section]):
                        if not isinstance(entry, dict):
                            continue
                        enforcement = entry.get("enforcement_mode")
                        if enforcement and isinstance(enforcement, dict):
                            for key in required_keys:
                                if key not in enforcement:
                                    drifts.append(Drift(
                                        drift_id=rule["id"],
                                        severity=rule["severity"],
                                        target_file=file,
                                        repo=repo,
                                        description=f"enforcement_mode missing key '{key}' in {section}[{idx}] ({entry.get('name', 'unknown')})",
                                        details={
                                            "section": section,
                                            "index": idx,
                                            "missing_key": key,
                                            "entry_name": entry.get('name', 'unknown')
                                        },
                                        auto_fixable=True,
                                        fix_action="merge_defaults",
                                        fix_details={"key": key}
                                    ))
        return drifts

    def _check_ternary_role_structure(
        self,
        repo: str,
        file: str,
        parsed: Any,
        rule: Dict,
        schemas: Dict
    ) -> List[Drift]:
        """Check ternary_role has correct structure."""
        drifts = []

        if isinstance(parsed, dict):
            for section in ["P0_REPOS", "P1_REPOS", "P2_REPOS", "P3_REPOS", "P4_REPOS", "P5_REPOS"]:
                if section in parsed:
                    for idx, entry in enumerate(parsed[section]):
                        if not isinstance(entry, dict):
                            continue
                        ternary = entry.get("ternary_role")
                        if ternary and isinstance(ternary, dict):
                            required_keys = ["primary", "secondary", "forbidden"]
                            for key in required_keys:
                                if key not in ternary:
                                    drifts.append(Drift(
                                        drift_id=rule["id"],
                                        severity=rule["severity"],
                                        target_file=file,
                                        repo=repo,
                                        description=f"ternary_role missing '{key}' in {section}[{idx}] ({entry.get('name', 'unknown')})",
                                        details={
                                            "section": section,
                                            "index": idx,
                                            "missing_key": key,
                                            "entry_name": entry.get('name', 'unknown')
                                        },
                                        auto_fixable=True,
                                        fix_action="set_default_structure",
                                        fix_details={"key": key}
                                    ))
        return drifts

    def _check_no_duplicate_entries(
        self,
        repo: str,
        file: str,
        parsed: Any,
        rule: Dict,
        schemas: Dict
    ) -> List[Drift]:
        """Check for duplicate full_name entries."""
        drifts = []
        seen = {}

        if isinstance(parsed, dict):
            for section in ["P0_REPOS", "P1_REPOS", "P2_REPOS", "P3_REPOS", "P4_REPOS", "P5_REPOS"]:
                if section in parsed:
                    for idx, entry in enumerate(parsed[section]):
                        if not isinstance(entry, dict):
                            continue
                        full_name = entry.get("full_name")
                        if full_name:
                            if full_name in seen:
                                drifts.append(Drift(
                                    drift_id=rule["id"],
                                    severity=rule["severity"],
                                    target_file=file,
                                    repo=repo,
                                    description=f"Duplicate full_name '{full_name}' found",
                                    details={
                                        "first_location": seen[full_name],
                                        "duplicate_location": {"section": section, "index": idx},
                                        "entry_name": entry.get('name', 'unknown')
                                    },
                                    auto_fixable=False
                                ))
                            else:
                                seen[full_name] = {"section": section, "index": idx}
        return drifts

    def scan_all(self) -> Dict[str, List[ScanResult]]:
        """Scan all configured repositories."""
        results = {}
        for target in self.targets["targets"]:
            repo_results = self.scan_repo(target["repo"])
            if repo_results:
                results[target["repo"]] = repo_results
        self.checkpoint["last_scan"] = datetime.utcnow().isoformat() + "Z"
        self._save_checkpoint()
        return results

    def get_auto_fixable_drifts(self, drifts: List[Drift]) -> List[Drift]:
        """Filter drifts that can be auto-fixed."""
        return [d for d in drifts if d.auto_fixable]

    def apply_fix(self, drift: Drift, dry_run: bool = True) -> Dict[str, Any]:
        """Apply an auto-fix for a drift."""
        result = {
            "drift_id": drift.drift_id,
            "success": False,
            "dry_run": dry_run,
            "action": drift.fix_action,
            "details": {}
        }

        if not drift.auto_fixable:
            result["error"] = "Drift is not auto-fixable"
            return result

        # Get the auto-fix rule
        auto_fix_rules = self.rules.get("auto_fix_rules", [])
        fix_rule = next((r for r in auto_fix_rules if r["drift_id"] == drift.drift_id), None)
        if not fix_rule:
            result["error"] = "No auto-fix rule found"
            return result

        # Apply fix based on action
        if drift.fix_action == "set_default":
            result["details"] = {"default_value": fix_rule.get("default_value")}
            result["success"] = True
        elif drift.fix_action == "add_field":
            result["details"] = {"default_value": fix_rule.get("default_value")}
            result["success"] = True
        elif drift.fix_action == "merge_defaults":
            result["details"] = {"default_enforcement": fix_rule.get("default_enforcement")}
            result["success"] = True
        elif drift.fix_action == "set_default_structure":
            result["details"] = {"default_structure": fix_rule.get("default_structure")}
            result["success"] = True
        elif drift.fix_action == "infer_path":
            result["details"] = {"inferred_from": drift.fix_details}
            result["success"] = True

        return result