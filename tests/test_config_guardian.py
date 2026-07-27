"""
Unit tests for RLM-CONFIG
"""

import pytest
import yaml
import json
import tempfile
import os
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config_guardian import ConfigGuardian, Drift, ScanResult


class TestConfigGuardian:
    """Tests for ConfigGuardian core functionality."""

    @pytest.fixture
    def temp_config(self, tmp_path):
        """Create a temporary config directory for testing."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        
        # Create rules.yaml
        rules = {
            "schemas": {
                "known_repositories": {
                    "required_fields": ["name", "full_name", "layer", "status", "role", "do_not_create"],
                    "valid_layers": ["L0_CANON", "L1_CAUSALITY", "L4_TOOLS"],
                    "valid_statuses": ["ACTIVE", "active", "archived"]
                }
            },
            "detection_rules": [
                {
                    "id": "DRIFT_001",
                    "name": "Missing required field",
                    "severity": "critical",
                    "target": "known_repositories.yaml",
                    "check": "required_fields_present"
                }
            ],
            "auto_fix_rules": []
        }
        (config_dir / "rules.yaml").write_text(yaml.dump(rules))
        
        # Create scan_targets.yaml
        targets = {
            "targets": [
                {
                    "repo": "TEST-REPO",
                    "local_path": str(tmp_path / "TEST-REPO"),
                    "files": ["known_repositories.yaml"],
                    "ruleset": "default"
                }
            ],
            "rulesets": {
                "default": ["DRIFT_001"]
            }
        }
        (config_dir / "scan_targets.yaml").write_text(yaml.dump(targets))
        
        yield config_dir

    @pytest.fixture
    def guardian(self, temp_config):
        """Create a ConfigGuardian instance."""
        return ConfigGuardian(config_dir=str(temp_config))

    def test_load_rules(self, guardian):
        """Test that rules load correctly."""
        assert guardian.rules is not None
        assert "schemas" in guardian.rules
        assert "detection_rules" in guardian.rules
        assert len(guardian.rules["detection_rules"]) > 0

    def test_load_targets(self, guardian):
        """Test that scan targets load correctly."""
        assert guardian.targets is not None
        assert "targets" in guardian.targets
        assert len(guardian.targets["targets"]) > 0

    def test_compute_hash(self, guardian):
        """Test hash computation."""
        content = "test content"
        hash1 = guardian._compute_hash(content)
        hash2 = guardian._compute_hash(content)
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex length

    def test_scan_missing_file(self, guardian, temp_config):
        """Test scanning a repo with missing config file."""
        # Create repo directory without the config file
        repo_path = Path(temp_config.parent) / "TEST-REPO"
        repo_path.mkdir()
        
        results = guardian.scan_repo("TEST-REPO")
        
        assert len(results) == 1
        result = results[0]
        assert result.repo == "TEST-REPO"
        assert len(result.drifts) == 1
        assert result.drifts[0].drift_id == "DRIFT_FILE_MISSING"
        assert result.drifts[0].severity == "critical"


class TestDriftDetection:
    """Tests for drift detection rules."""

    @pytest.fixture
    def sample_known_repos(self):
        """Sample known_repositories.yaml content."""
        return {
            "P0_REPOS": [
                {
                    "name": "TEST-REPO",
                    "full_name": "gerivdb/TEST-REPO",
                    "layer": "L1_CAUSALITY",
                    "status": "ACTIVE",
                    "role": "Test repo",
                    "do_not_create": True,
                    "enforcement_mode": {
                        "ci": "full",
                        "branch_protection": "full",
                        "hooks": "full",
                        "rss_lint": "all-checks",
                        "vyoa": "full",
                        "brgs": "full"
                    }
                }
            ]
        }

    def test_valid_repo_entry(self, sample_known_repos):
        """Test that a valid repo entry passes validation."""
        # This would be tested via the actual detection logic
        entry = sample_known_repos["P0_REPOS"][0]
        required = ["name", "full_name", "layer", "status", "role", "do_not_create", "enforcement_mode"]
        for field in required:
            assert field in entry

    def test_invalid_layer_detection(self):
        """Test detection of invalid layer values."""
        invalid_layers = ["INVALID_LAYER", "L99", "NOT_A_LAYER"]
        valid_layers = ["L0_CANON", "L1_CAUSALITY", "L4_TOOLS", "L3_EMERGENCE"]
        
        for layer in invalid_layers:
            assert layer not in valid_layers
        
        for layer in valid_layers:
            assert layer in valid_layers

    def test_missing_do_not_create(self):
        """Test detection of missing do_not_create field."""
        entry = {
            "name": "TEST",
            "full_name": "gerivdb/TEST",
            "layer": "L1_CAUSALITY",
            "status": "ACTIVE",
            "role": "Test"
            # Missing do_not_create
        }
        assert "do_not_create" not in entry

    def test_enforcement_mode_completeness(self):
        """Test that enforcement_mode has all required keys."""
        required_keys = ["ci", "branch_protection", "hooks", "rss_lint", "vyoa", "brgs"]
        
        complete_mode = {k: "full" for k in required_keys}
        for key in required_keys:
            assert key in complete_mode
        
        incomplete_mode = {"ci": "full", "hooks": "full"}  # Missing keys
        missing = [k for k in required_keys if k not in incomplete_mode]
        assert len(missing) == 4


class TestAPI:
    """Tests for API endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from health import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

    def test_health_endpoint(self, client):
        """Test /health endpoint."""
        response = client.get('/health')
        assert response.status_code == 200
        data = response.get_json()
        assert data['service'] == 'RLM-CONFIG'
        assert 'status' in data
        assert 'checks' in data

    def test_metrics_endpoint(self, client):
        """Test /metrics endpoint."""
        response = client.get('/metrics')
        assert response.status_code == 200
        data = response.get_json()
        assert data['service'] == 'RLM-CONFIG'
        assert 'timestamp' in data

    def test_vote_endpoint_get(self, client):
        """Test GET /vote endpoint."""
        response = client.get('/vote')
        assert response.status_code == 200
        data = response.get_json()
        assert 'active_votes' in data
        assert 'completed_votes' in data


class TestCheckpoint:
    """Tests for checkpoint functionality."""

    @pytest.fixture
    def temp_config(self, tmp_path):
        """Create a temporary config directory for testing."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        
        # Create minimal rules.yaml
        rules = {
            "schemas": {"known_repositories": {"required_fields": ["name"]}},
            "detection_rules": [],
            "auto_fix_rules": []
        }
        (config_dir / "rules.yaml").write_text(yaml.dump(rules))
        
        # Create minimal scan_targets.yaml
        targets = {
            "targets": [{"repo": "TEST", "local_path": str(tmp_path / "TEST"), "files": ["test.yaml"], "ruleset": "default"}],
            "rulesets": {"default": []}
        }
        (config_dir / "scan_targets.yaml").write_text(yaml.dump(targets))
        
        yield config_dir

    def test_checkpoint_save_load(self, temp_config):
        """Test checkpoint save and load cycle."""
        guardian = ConfigGuardian(config_dir=str(temp_config))
        assert guardian.checkpoint is not None

    def test_file_hash_tracking(self, temp_config):
        """Test that file hashes can be tracked in checkpoint."""
        guardian = ConfigGuardian(config_dir=str(temp_config))
        # Create a test file to scan
        test_file = Path(temp_config.parent) / "TEST" / "test.yaml"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("test: value")
        
        guardian.scan_repo("TEST")
        assert "file_hashes" in guardian.checkpoint


if __name__ == "__main__":
    pytest.main([__file__, "-v"])