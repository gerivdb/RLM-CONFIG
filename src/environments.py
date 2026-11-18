"""
RLM-CONFIG - Environment Configuration Management
Manages environment-specific configurations with inheritance, validation, and distribution.
"""

import json
import threading
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional, Union
from enum import Enum


class EnvironmentName(Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TESTING = "testing"


class ConfigType(Enum):
    SERVICE = "service"
    SHARED = "shared"
    INFRASTRUCTURE = "infrastructure"
    SECURITY = "security"


@dataclass
class ConfigSchema:
    key: str
    type: str  # string, number, boolean, object, array
    required: bool = False
    default: Any = None
    description: str = ""
    validation: Dict[str, Any] = field(default_factory=dict)
    sensitive: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EnvironmentConfig:
    id: str
    name: EnvironmentName
    display_name: str
    description: str
    parent: Optional[str] = None
    configs: Dict[str, Any] = field(default_factory=dict)
    schemas: Dict[str, ConfigSchema] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    created_by: str = "system"
    updated_by: str = "system"
    version: int = 1
    locked: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['name'] = self.name.value
        d['schemas'] = {k: v.to_dict() for k, v in self.schemas.items()}
        return d


@dataclass
class ConfigVersion:
    environment_id: str
    version: int
    configs: Dict[str, Any]
    changed_by: str
    changed_at: str
    change_summary: str
    previous_version: int


class EnvironmentStore:
    def __init__(self, storage_dir: str = "config/environments"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.envs_file = self.storage_dir / "environments.json"
        self.versions_file = self.storage_dir / "versions.json"
        self._lock = threading.RLock()
        self._environments: Dict[str, EnvironmentConfig] = {}
        self._versions: Dict[str, List[ConfigVersion]] = {}
        self._load()

    def _load(self):
        with self._lock:
            if self.envs_file.exists():
                with open(self.envs_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for env_data in data.get('environments', []):
                        env = self._deserialize_env(env_data)
                        self._environments[env.id] = env
            if self.versions_file.exists():
                with open(self.versions_file, 'r', encoding='utf-8') as f:
                    versions_data = json.load(f)
                    self._versions = {k: [ConfigVersion(**v) for v in vs] for k, vs in versions_data.items()}

    def _save_envs(self):
        with self._lock:
            data = {'environments': [e.to_dict() for e in self._environments.values()]}
            with open(self.envs_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

    def _save_versions(self):
        with self._lock:
            data = {k: [asdict(v) for v in vs] for k, vs in self._versions.items()}
            with open(self.versions_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

    def _deserialize_env(self, data: Dict[str, Any]) -> EnvironmentConfig:
        schemas = {}
        for k, v in data.get('schemas', {}).items():
            schemas[k] = ConfigSchema(**v)
        return EnvironmentConfig(
            id=data['id'],
            name=EnvironmentName(data['name']),
            display_name=data['display_name'],
            description=data['description'],
            parent=data.get('parent'),
            configs=data.get('configs', {}),
            schemas=schemas,
            metadata=data.get('metadata', {}),
            created_at=data.get('created_at', datetime.now(timezone.utc).isoformat()),
            updated_at=data.get('updated_at', datetime.now(timezone.utc).isoformat()),
            created_by=data.get('created_by', 'system'),
            updated_by=data.get('updated_by', 'system'),
            version=data.get('version', 1),
            locked=data.get('locked', False)
        )

    def create_environment(self, env: EnvironmentConfig) -> EnvironmentConfig:
        with self._lock:
            if env.name.value in [e.name.value for e in self._environments.values()]:
                raise ValueError(f"Environment '{env.name.value}' already exists")
            self._environments[env.id] = env
            self._save_envs()
            return env

    def get_environment(self, env_id: str) -> Optional[EnvironmentConfig]:
        with self._lock:
            return self._environments.get(env_id)

    def get_environment_by_name(self, name: EnvironmentName) -> Optional[EnvironmentConfig]:
        with self._lock:
            for env in self._environments.values():
                if env.name == name:
                    return env
            return None

    def list_environments(self) -> List[EnvironmentConfig]:
        with self._lock:
            return list(self._environments.values())

    def update_environment(self, env_id: str, updates: Dict[str, Any], updated_by: str = "system") -> Optional[EnvironmentConfig]:
        with self._lock:
            env = self._environments.get(env_id)
            if not env:
                return None
            if env.locked:
                raise ValueError(f"Environment '{env.name.value}' is locked")
            
            old_configs = env.configs.copy()
            old_version = env.version
            
            for key, value in updates.items():
                if key == 'name':
                    env.name = EnvironmentName(value)
                elif key == 'configs':
                    env.configs = {**env.configs, **value}
                elif key == 'schemas':
                    schemas = {}
                    for k, v in value.items():
                        schemas[k] = ConfigSchema(**v)
                    env.schemas = {**env.schemas, **schemas}
                elif hasattr(env, key):
                    setattr(env, key, value)
            
            env.updated_at = datetime.now(timezone.utc).isoformat()
            env.updated_by = updated_by
            env.version += 1
            
            self._add_version(env_id, old_configs, updated_by, f"Updated: {list(updates.keys())}", old_version)
            self._save_envs()
            return env

    def set_config(self, env_id: str, key: str, value: Any, updated_by: str = "system") -> bool:
        with self._lock:
            env = self._environments.get(env_id)
            if not env:
                return False
            if env.locked:
                raise ValueError(f"Environment '{env.name.value}' is locked")
            
            if key in env.schemas:
                schema = env.schemas[key]
                if not self._validate_value(value, schema):
                    raise ValueError(f"Value for '{key}' does not match schema")
            
            old_configs = env.configs.copy()
            old_version = env.version
            env.configs[key] = value
            env.updated_at = datetime.now(timezone.utc).isoformat()
            env.updated_by = updated_by
            env.version += 1
            
            self._add_version(env_id, old_configs, updated_by, f"Set config '{key}'", old_version)
            self._save_envs()
            return True

    def get_config(self, env_id: str, key: str) -> Any:
        with self._lock:
            env = self._environments.get(env_id)
            if not env:
                return None
            
            if key in env.configs:
                return env.configs[key]
            if env.parent:
                parent = self.get_environment(env.parent)
                if parent:
                    return self.get_config(parent.id, key)
            return None

    def get_all_configs(self, env_id: str, include_inherited: bool = True) -> Dict[str, Any]:
        with self._lock:
            env = self._environments.get(env_id)
            if not env:
                return {}
            
            configs = env.configs.copy()
            if include_inherited and env.parent:
                parent = self.get_environment(env.parent)
                if parent:
                    parent_configs = self.get_all_configs(parent.id, include_inherited)
                    # Parent configs are overridden by child
                    configs = {**parent_configs, **configs}
            return configs

    def _validate_value(self, value: Any, schema: ConfigSchema) -> bool:
        if value is None and not schema.required:
            return True
        
        type_map = {
            'string': str,
            'number': (int, float),
            'boolean': bool,
            'object': dict,
            'array': list
        }
        
        expected_type = type_map.get(schema.type)
        if expected_type and not isinstance(value, expected_type):
            return False
        
        validation = schema.validation
        if 'enum' in validation and value not in validation['enum']:
            return False
        if 'min' in validation and isinstance(value, (int, float)) and value < validation['min']:
            return False
        if 'max' in validation and isinstance(value, (int, float)) and value > validation['max']:
            return False
        if 'pattern' in validation and isinstance(value, str):
            import re
            if not re.match(validation['pattern'], value):
                return False
        return True

    def _add_version(self, env_id: str, old_configs: Dict, changed_by: str, summary: str, old_version: int):
        version = ConfigVersion(
            environment_id=env_id,
            version=old_version + 1,
            configs=old_configs,
            changed_by=changed_by,
            changed_at=datetime.now(timezone.utc).isoformat(),
            change_summary=summary,
            previous_version=old_version
        )
        if env_id not in self._versions:
            self._versions[env_id] = []
        self._versions[env_id].append(version)
        if len(self._versions[env_id]) > 100:
            self._versions[env_id] = self._versions[env_id][-100:]
        self._save_versions()

    def get_versions(self, env_id: str, limit: int = 20) -> List[ConfigVersion]:
        with self._lock:
            versions = self._versions.get(env_id, [])
            return versions[-limit:]

    def rollback(self, env_id: str, target_version: int, rolled_back_by: str = "system") -> bool:
        with self._lock:
            env = self._environments.get(env_id)
            if not env:
                return False
            if env.locked:
                raise ValueError(f"Environment '{env.name.value}' is locked")
            
            versions = self._versions.get(env_id, [])
            target = next((v for v in versions if v.version == target_version), None)
            if not target:
                return False
            
            old_configs = env.configs.copy()
            old_version = env.version
            
            env.configs = target.configs
            env.updated_at = datetime.now(timezone.utc).isoformat()
            env.updated_by = rolled_back_by
            env.version += 1
            
            self._add_version(env_id, old_configs, rolled_back_by, f"Rollback to version {target_version}", old_version)
            self._save_envs()
            return True


# Default environment configurations
def create_default_environments(store: EnvironmentStore) -> List[EnvironmentConfig]:
    environments = []
    
    # Development environment
    dev_env = EnvironmentConfig(
        id=str(uuid.uuid4()),
        name=EnvironmentName.DEVELOPMENT,
        display_name="Development",
        description="Local development environment with relaxed settings",
        configs={
            # Core ecosystem settings
            "ecosystem": {
                "name": "gerivdb-dev",
                "mode": "development",
                "debug": True
            },
            # Runner settings
            "runners": {
                "auto_start": True,
                "default_port_range": "8780-8800",
                "health_check_interval": 30
            },
            # KIX orchestrator
            "kix": {
                "enabled": True,
                "jwt_secret": "dev-secret-change-in-production",
                "vote_threshold": 2,
                "circuit_breaker_threshold": 3
            },
            # RLM-243
            "rlm243": {
                "phi_cps_threshold": 4.559,
                "latency_ms_threshold": 100,
                "power_w_threshold": 200
            },
            # RLM-CONFIG
            "rlm_config": {
                "scan_interval_minutes": 5,
                "auto_fix_enabled": True,
                "drift_severity_threshold": "low"
            },
            # RLM-GRAPH
            "rlm_graph": {
                "backend": "memory",
                "duckdb_path": null,
                "max_depth": 5
            },
            # RLM-DEPLOY
            "rlm_deploy": {
                "default_strategy": "blue_green",
                "canary_percentage": 10,
                "health_check_timeout": 30
            },
            # RLM-SECURE
            "rlm_secure": {
                "scan_types": ["secrets", "vulnerabilities", "opa"],
                "fail_on_critical": False,
                "fail_on_high": False
            },
            # RLM-INCIDENT
            "rlm_incident": {
                "auto_trigger_playbooks": True,
                "notification_channels": ["console"],
                "sla_minutes": 60
            },
            # RLM-RELEASE
            "rlm_release": {
                "auto_version_bump": True,
                "generate_changelog": True,
                "conventional_commits": True
            },
            # RLM-MDU
            "rlm_mdu": {
                "friction_detection": True,
                "auto_fix_safe": True,
                "escalation_threshold": 3
            },
            # MIMIR
            "mimir": {
                "retention_days": 7,
                "aggregation_interval": 60,
                "anomaly_detection": False
            },
            # BDCP
            "bdcp": {
                "enabled": False,
                "clapet_closed": True,
                "fallback_only": True
            },
            # Feature flags
            "feature_flags": {
                "auto_remediation": True,
                "cross_rlm_voting": True,
                "strict_phi_cps": False,
                "bdcp_strict": False
            },
            # Logging
            "logging": {
                "level": "DEBUG",
                "format": "json",
                "output": "console"
            }
        },
        schemas={
            "ecosystem": ConfigSchema("ecosystem", "object", description="Core ecosystem settings"),
            "runners": ConfigSchema("runners", "object", description="Runner management settings"),
            "kix": ConfigSchema("kix", "object", description="KIX orchestrator settings"),
            "rlm243": ConfigSchema("rlm243", "object", description="RLM-243 validation thresholds"),
            "rlm_config": ConfigSchema("rlm_config", "object", description="RLM-CONFIG scan settings"),
            "rlm_graph": ConfigSchema("rlm_graph", "object", description="RLM-GRAPH backend settings"),
            "rlm_deploy": ConfigSchema("rlm_deploy", "object", description="RLM-DEPLOY deployment settings"),
            "rlm_secure": ConfigSchema("rlm_secure", "object", description="RLM-SECURE scan settings"),
            "rlm_incident": ConfigSchema("rlm_incident", "object", description="RLM-INCIDENT incident settings"),
            "rlm_release": ConfigSchema("rlm_release", "object", description="RLM-RELEASE release settings"),
            "rlm_mdu": ConfigSchema("rlm_mdu", "object", description="RLM-MDU friction detection settings"),
            "mimir": ConfigSchema("mimir", "object", description="MIMIR monitoring settings"),
            "bdcp": ConfigSchema("bdcp", "object", description="BDCP network protection settings"),
            "feature_flags": ConfigSchema("feature_flags", "object", description="Feature flag overrides"),
            "logging": ConfigSchema("logging", "object", description="Logging configuration")
        },
        metadata={"tier": "development", "color": "blue"}
    )
    
    # Staging environment (inherits from development)
    staging_env = EnvironmentConfig(
        id=str(uuid.uuid4()),
        name=EnvironmentName.STAGING,
        display_name="Staging",
        description="Pre-production staging environment",
        parent=dev_env.id,
        configs={
            "ecosystem": {
                "name": "gerivdb-staging",
                "mode": "staging",
                "debug": False
            },
            "runners": {
                "health_check_interval": 60
            },
            "kix": {
                "vote_threshold": 2,
                "circuit_breaker_threshold": 5
            },
            "rlm243": {
                "latency_ms_threshold": 50,
                "power_w_threshold": 150
            },
            "rlm_config": {
                "scan_interval_minutes": 15,
                "auto_fix_enabled": False
            },
            "rlm_secure": {
                "fail_on_critical": True,
                "fail_on_high": True
            },
            "rlm_incident": {
                "notification_channels": ["console", "webhook"]
            },
            "bdcp": {
                "enabled": True,
                "clapet_closed": True
            },
            "feature_flags": {
                "auto_remediation": True,
                "cross_rlm_voting": True,
                "strict_phi_cps": True,
                "bdcp_strict": True
            },
            "logging": {
                "level": "INFO"
            }
        },
        metadata={"tier": "staging", "color": "yellow"}
    )
    
    # Production environment (inherits from staging)
    prod_env = EnvironmentConfig(
        id=str(uuid.uuid4()),
        name=EnvironmentName.PRODUCTION,
        display_name="Production",
        description="Production environment with strict settings",
        parent=staging_env.id,
        configs={
            "ecosystem": {
                "name": "gerivdb-prod",
                "mode": "production",
                "debug": False
            },
            "runners": {
                "health_check_interval": 120
            },
            "kix": {
                "vote_threshold": 3,
                "circuit_breaker_threshold": 2
            },
            "rlm243": {
                "latency_ms_threshold": 10,
                "power_w_threshold": 100
            },
            "rlm_config": {
                "scan_interval_minutes": 30,
                "auto_fix_enabled": False
            },
            "rlm_secure": {
                "fail_on_critical": True,
                "fail_on_high": True
            },
            "rlm_incident": {
                "auto_trigger_playbooks": True,
                "notification_channels": ["console", "webhook", "email"],
                "sla_minutes": 15
            },
            "rlm_release": {
                "auto_version_bump": True,
                "push_tags": True
            },
            "bdcp": {
                "enabled": True,
                "clapet_closed": True,
                "fallback_only": True
            },
            "feature_flags": {
                "auto_remediation": False,
                "cross_rlm_voting": True,
                "strict_phi_cps": True,
                "bdcp_strict": True
            },
            "logging": {
                "level": "WARNING",
                "output": "file"
            }
        },
        locked=True,
        metadata={"tier": "production", "color": "red"}
    )
    
    # Testing environment (independent)
    test_env = EnvironmentConfig(
        id=str(uuid.uuid4()),
        name=EnvironmentName.TESTING,
        display_name="Testing",
        description="Automated testing environment",
        configs={
            "ecosystem": {
                "name": "gerivdb-test",
                "mode": "testing",
                "debug": True
            },
            "runners": {
                "auto_start": True,
                "default_port_range": "8780-8800"
            },
            "rlm_config": {
                "scan_interval_minutes": 1,
                "auto_fix_enabled": True
            },
            "feature_flags": {
                "auto_remediation": True,
                "cross_rlm_voting": False,
                "strict_phi_cps": False
            }
        },
        metadata={"tier": "testing", "color": "green"}
    )
    
    for env in [dev_env, staging_env, prod_env, test_env]:
        try:
            store.create_environment(env)
            environments.append(env)
        except ValueError:
            existing = store.get_environment_by_name(env.name)
            if existing:
                environments.append(existing)
    
    return environments