"""
RLM-CONFIG - Feature Flags Management
Centralized feature flag service with environment support, rollout strategies, and audit.
"""

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional, Union
from enum import Enum


class Environment(Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TESTING = "testing"


class RolloutStrategy(Enum):
    ALL = "all"
    PERCENTAGE = "percentage"
    USER_LIST = "user_list"
    CONDITIONAL = "conditional"


class FeatureFlagStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


@dataclass
class RolloutConfig:
    strategy: RolloutStrategy = RolloutStrategy.ALL
    percentage: float = 100.0
    user_ids: List[str] = field(default_factory=list)
    conditions: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FeatureFlag:
    id: str
    key: str
    name: str
    description: str
    enabled: bool
    status: FeatureFlagStatus
    environment: Environment
    rollout: RolloutConfig
    tags: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    created_by: str = "system"
    updated_by: str = "system"
    version: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['environment'] = self.environment.value
        d['status'] = self.status.value
        d['rollout'] = {
            'strategy': self.rollout.strategy.value,
            'percentage': self.rollout.percentage,
            'user_ids': self.rollout.user_ids,
            'conditions': self.rollout.conditions
        }
        return d


@dataclass
class FeatureFlagHistory:
    flag_id: str
    action: str
    old_value: Dict[str, Any]
    new_value: Dict[str, Any]
    changed_by: str
    timestamp: str
    version: int


class FeatureFlagsStore:
    def __init__(self, storage_dir: str = "config/feature_flags"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.flags_file = self.storage_dir / "flags.json"
        self.history_file = self.storage_dir / "history.json"
        self._lock = threading.RLock()
        self._flags: Dict[str, FeatureFlag] = {}
        self._history: List[Dict[str, Any]] = []
        self._load()

    def _load(self):
        with self._lock:
            if self.flags_file.exists():
                with open(self.flags_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for flag_data in data.get('flags', []):
                        flag = self._deserialize_flag(flag_data)
                        self._flags[flag.id] = flag
            if self.history_file.exists():
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    self._history = json.load(f)

    def _save_flags(self):
        with self._lock:
            data = {'flags': [f.to_dict() for f in self._flags.values()]}
            with open(self.flags_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

    def _save_history(self):
        with self._lock:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(self._history, f, indent=2)

    def _deserialize_flag(self, data: Dict[str, Any]) -> FeatureFlag:
        rollout_data = data.get('rollout', {})
        rollout = RolloutConfig(
            strategy=RolloutStrategy(rollout_data.get('strategy', 'all')),
            percentage=rollout_data.get('percentage', 100.0),
            user_ids=rollout_data.get('user_ids', []),
            conditions=rollout_data.get('conditions', {})
        )
        return FeatureFlag(
            id=data['id'],
            key=data['key'],
            name=data['name'],
            description=data['description'],
            enabled=data['enabled'],
            status=FeatureFlagStatus(data['status']),
            environment=Environment(data['environment']),
            rollout=rollout,
            tags=data.get('tags', []),
            created_at=data.get('created_at', ''),
            updated_at=data.get('updated_at', ''),
            created_by=data.get('created_by', 'system'),
            updated_by=data.get('updated_by', 'system'),
            version=data.get('version', 1),
            metadata=data.get('metadata', {})
        )

    def _add_history(self, flag: FeatureFlag, action: str, old_value: Dict[str, Any], changed_by: str):
        entry = {
            'flag_id': flag.id,
            'action': action,
            'old_value': old_value,
            'new_value': flag.to_dict(),
            'changed_by': changed_by,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'version': flag.version
        }
        self._history.append(entry)
        if len(self._history) > 1000:
            self._history = self._history[-1000:]
        self._save_history()

    def create_flag(self, flag: FeatureFlag) -> FeatureFlag:
        with self._lock:
            if any(f.key == flag.key and f.environment == flag.environment for f in self._flags.values()):
                raise ValueError(f"Flag with key '{flag.key}' already exists in environment '{flag.environment.value}'")
            self._flags[flag.id] = flag
            self._save_flags()
            self._add_history(flag, 'create', {}, flag.created_by)
            return flag

    def get_flag(self, flag_id: str) -> Optional[FeatureFlag]:
        with self._lock:
            return self._flags.get(flag_id)

    def get_flag_by_key(self, key: str, environment: Environment) -> Optional[FeatureFlag]:
        with self._lock:
            for flag in self._flags.values():
                if flag.key == key and flag.environment == environment:
                    return flag
            return None

    def list_flags(self, environment: Optional[Environment] = None, status: Optional[FeatureFlagStatus] = None) -> List[FeatureFlag]:
        with self._lock:
            flags = list(self._flags.values())
            if environment:
                flags = [f for f in flags if f.environment == environment]
            if status:
                flags = [f for f in flags if f.status == status]
            return sorted(flags, key=lambda f: (f.environment.value, f.key))

    def update_flag(self, flag_id: str, updates: Dict[str, Any], updated_by: str = "system") -> Optional[FeatureFlag]:
        with self._lock:
            flag = self._flags.get(flag_id)
            if not flag:
                return None
            old_value = flag.to_dict()
            
            if 'enabled' in updates:
                flag.enabled = updates['enabled']
            if 'status' in updates:
                flag.status = FeatureFlagStatus(updates['status']) if isinstance(updates['status'], str) else updates['status']
            if 'rollout' in updates:
                rollout_data = updates['rollout']
                flag.rollout = RolloutConfig(
                    strategy=RolloutStrategy(rollout_data.get('strategy', 'all')),
                    percentage=rollout_data.get('percentage', 100.0),
                    user_ids=rollout_data.get('user_ids', []),
                    conditions=rollout_data.get('conditions', {})
                )
            if 'tags' in updates:
                flag.tags = updates['tags']
            if 'metadata' in updates:
                flag.metadata = updates['metadata']
            if 'description' in updates:
                flag.description = updates['description']
            if 'name' in updates:
                flag.name = updates['name']
            
            flag.version += 1
            flag.updated_at = datetime.now(timezone.utc).isoformat()
            flag.updated_by = updated_by
            
            self._save_flags()
            self._add_history(flag, 'update', old_value, updated_by)
            return flag

    def delete_flag(self, flag_id: str, deleted_by: str = "system") -> bool:
        with self._lock:
            flag = self._flags.get(flag_id)
            if not flag:
                return False
            old_value = flag.to_dict()
            del self._flags[flag_id]
            self._save_flags()
            self._add_history(flag, 'delete', old_value, deleted_by)
            return True

    def evaluate_flag(self, key: str, environment: Environment, context: Dict[str, Any] = None) -> bool:
        """Evaluate a feature flag for a given context."""
        flag = self.get_flag_by_key(key, environment)
        if not flag or flag.status != FeatureFlagStatus.ACTIVE:
            return False
        
        if not flag.enabled:
            return False
        
        context = context or {}
        
        # Check rollout strategy
        if flag.rollout.strategy == RolloutStrategy.ALL:
            return True
        elif flag.rollout.strategy == RolloutStrategy.PERCENTAGE:
            # Use user_id or session_id for consistent hashing
            user_id = context.get('user_id', context.get('session_id', 'anonymous'))
            hash_val = hash(f"{flag.key}:{user_id}") % 100
            return hash_val < flag.rollout.percentage
        elif flag.rollout.strategy == RolloutStrategy.USER_LIST:
            user_id = context.get('user_id', context.get('session_id', ''))
            return user_id in flag.rollout.user_ids
        elif flag.rollout.strategy == RolloutStrategy.CONDITIONAL:
            # Simple condition evaluation
            for cond_key, cond_value in flag.rollout.conditions.items():
                if context.get(cond_key) != cond_value:
                    return False
            return True
        
        return False

    def get_history(self, flag_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            flag_history = [h for h in self._history if h['flag_id'] == flag_id]
            return flag_history[-limit:]

    def get_all_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            return self._history[-limit:]


# Default feature flags for the ecosystem
def create_default_flags(store: FeatureFlagsStore) -> List[FeatureFlag]:
    flags = []
    
    for env in Environment:
        # Auto-remediation
        flags.append(FeatureFlag(
            id=str(uuid.uuid4()),
            key="auto_remediation_enabled",
            name="Auto Remediation",
            description="Enable automatic remediation of detected incidents",
            enabled=env != Environment.PRODUCTION,
            status=FeatureFlagStatus.ACTIVE,
            environment=env,
            rollout=RolloutConfig(strategy=RolloutStrategy.ALL),
            tags=["incident", "automation"],
            created_by="system"
        ))
        
        # Strict φ-CPS validation
        flags.append(FeatureFlag(
            id=str(uuid.uuid4()),
            key="strict_phi_cps",
            name="Strict φ-CPS Validation",
            description="Enforce strict φ-CPS thresholds for all runners",
            enabled=env in [Environment.STAGING, Environment.PRODUCTION],
            status=FeatureFlagStatus.ACTIVE,
            environment=env,
            rollout=RolloutConfig(strategy=RolloutStrategy.ALL),
            tags=["validation", "phi-cps"],
            created_by="system"
        ))
        
        # BDCP strict mode
        flags.append(FeatureFlag(
            id=str(uuid.uuid4()),
            key="bdcp_strict_mode",
            name="BDCP Strict Mode",
            description="Enforce BDCP mode - no external network access",
            enabled=env == Environment.PRODUCTION,
            status=FeatureFlagStatus.ACTIVE,
            environment=env,
            rollout=RolloutConfig(strategy=RolloutStrategy.ALL),
            tags=["security", "bdcp"],
            created_by="system"
        ))
        
        # New runner registration
        flags.append(FeatureFlag(
            id=str(uuid.uuid4()),
            key="new_runner_registration",
            name="New Runner Registration",
            description="Allow new runners to register with KIX",
            enabled=env in [Environment.DEVELOPMENT, Environment.STAGING],
            status=FeatureFlagStatus.ACTIVE,
            environment=env,
            rollout=RolloutConfig(strategy=RolloutStrategy.ALL),
            tags=["kix", "runner"],
            created_by="system"
        ))
        
        # Cross-RLM distributed voting
        flags.append(FeatureFlag(
            id=str(uuid.uuid4()),
            key="cross_rlm_voting",
            name="Cross-RLM Distributed Voting",
            description="Enable distributed ternary voting across RLM services",
            enabled=env in [Environment.STAGING, Environment.PRODUCTION],
            status=FeatureFlagStatus.ACTIVE,
            environment=env,
            rollout=RolloutConfig(strategy=RolloutStrategy.PERCENTAGE, percentage=50.0),
            tags=["rlm", "voting", "distributed"],
            created_by="system"
        ))
        
        # MIMIR advanced analytics
        flags.append(FeatureFlag(
            id=str(uuid.uuid4()),
            key="mimir_advanced_analytics",
            name="MIMIR Advanced Analytics",
            description="Enable advanced analytics and ML-based anomaly detection in MIMIR",
            enabled=env in [Environment.DEVELOPMENT, Environment.STAGING],
            status=FeatureFlagStatus.INACTIVE,
            environment=env,
            rollout=RolloutConfig(strategy=RolloutStrategy.ALL),
            tags=["mimir", "analytics", "ml"],
            created_by="system"
        ))
        
        # Configuration drift auto-fix
        flags.append(FeatureFlag(
            id=str(uuid.uuid4()),
            key="config_drift_auto_fix",
            name="Configuration Drift Auto-Fix",
            description="Automatically fix detected configuration drifts",
            enabled=env in [Environment.DEVELOPMENT, Environment.TESTING],
            status=FeatureFlagStatus.ACTIVE,
            environment=env,
            rollout=RolloutConfig(strategy=RolloutStrategy.ALL),
            tags=["config", "drift", "automation"],
            created_by="system"
        ))
    
    # Create in store
    created = []
    for flag in flags:
        try:
            existing = store.get_flag_by_key(flag.key, flag.environment)
            if not existing:
                store.create_flag(flag)
                created.append(flag)
            else:
                created.append(existing)
        except ValueError:
            existing = store.get_flag_by_key(flag.key, flag.environment)
            if existing:
                created.append(existing)
    
    return created