"""
RLM-CONFIG - Configuration Distribution
Manages distribution of configurations to services via push/pull mechanisms.
"""

import json
import threading
import uuid
import hashlib
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable
from enum import Enum


class DistributionMethod(Enum):
    PUSH = "push"          # Active push to service endpoints
    PULL = "pull"          # Services poll for changes
    WEBHOOK = "webhook"    # Webhook notifications


class DistributionStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass
class ServiceEndpoint:
    id: str
    name: str
    type: str  # rlm, kix, mimir, custom
    base_url: str
    health_endpoint: str = "/health"
    config_endpoint: str = "/config"
    method: DistributionMethod = DistributionMethod.PUSH
    environments: List[str] = field(default_factory=list)
    headers: Dict[str, str] = field(default_factory=dict)
    timeout_seconds: int = 30
    retry_count: int = 3
    retry_delay_seconds: int = 5
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['method'] = self.method.value
        return d


@dataclass
class ConfigDistribution:
    id: str
    environment_id: str
    environment_name: str
    configs: Dict[str, Any]
    version: int
    status: DistributionStatus
    targets: List[str]  # Service endpoint IDs
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    results: Dict[str, Any] = field(default_factory=dict)
    checksum: str = ""
    triggered_by: str = "system"
    rollback_version: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DistributionResult:
    distribution_id: str
    endpoint_id: str
    endpoint_name: str
    success: bool
    status_code: Optional[int] = None
    response: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DistributionStore:
    def __init__(self, storage_dir: str = "config/distribution"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.endpoints_file = self.storage_dir / "endpoints.json"
        self.distributions_file = self.storage_dir / "distributions.json"
        self._lock = threading.RLock()
        self._endpoints: Dict[str, ServiceEndpoint] = {}
        self._distributions: Dict[str, ConfigDistribution] = {}
        self._load()

    def _load(self):
        with self._lock:
            if self.endpoints_file.exists():
                with open(self.endpoints_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for ep_data in data.get('endpoints', []):
                        ep = self._deserialize_endpoint(ep_data)
                        self._endpoints[ep.id] = ep
            if self.distributions_file.exists():
                with open(self.distributions_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for dist_data in data.get('distributions', []):
                        dist = self._deserialize_distribution(dist_data)
                        self._distributions[dist.id] = dist

    def _save_endpoints(self):
        with self._lock:
            data = {'endpoints': [e.to_dict() for e in self._endpoints.values()]}
            with open(self.endpoints_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

    def _save_distributions(self):
        with self._lock:
            data = {'distributions': [d.__dict__ for d in self._distributions.values()]}
            with open(self.distributions_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, default=str)

    def _deserialize_endpoint(self, data: Dict[str, Any]) -> ServiceEndpoint:
        return ServiceEndpoint(
            id=data['id'],
            name=data['name'],
            type=data['type'],
            base_url=data['base_url'],
            health_endpoint=data.get('health_endpoint', '/health'),
            config_endpoint=data.get('config_endpoint', '/config'),
            method=DistributionMethod(data.get('method', 'push')),
            environments=data.get('environments', []),
            headers=data.get('headers', {}),
            timeout_seconds=data.get('timeout_seconds', 30),
            retry_count=data.get('retry_count', 3),
            retry_delay_seconds=data.get('retry_delay_seconds', 5),
            metadata=data.get('metadata', {}),
            created_at=data.get('created_at', datetime.now(timezone.utc).isoformat()),
            updated_at=data.get('updated_at', datetime.now(timezone.utc).isoformat())
        )

    def _deserialize_distribution(self, data: Dict[str, Any]) -> ConfigDistribution:
        return ConfigDistribution(
            id=data['id'],
            environment_id=data['environment_id'],
            environment_name=data['environment_name'],
            configs=data['configs'],
            version=data['version'],
            status=DistributionStatus(data['status']),
            targets=data['targets'],
            started_at=data.get('started_at'),
            completed_at=data.get('completed_at'),
            results=data.get('results', {}),
            checksum=data.get('checksum', ''),
            triggered_by=data.get('triggered_by', 'system'),
            rollback_version=data.get('rollback_version'),
            metadata=data.get('metadata', {})
        )

    def register_endpoint(self, endpoint: ServiceEndpoint) -> ServiceEndpoint:
        with self._lock:
            # Check for duplicate name
            if any(e.name == endpoint.name for e in self._endpoints.values()):
                raise ValueError(f"Endpoint with name '{endpoint.name}' already exists")
            self._endpoints[endpoint.id] = endpoint
            self._save_endpoints()
            return endpoint

    def get_endpoint(self, endpoint_id: str) -> Optional[ServiceEndpoint]:
        with self._lock:
            return self._endpoints.get(endpoint_id)

    def get_endpoint_by_name(self, name: str) -> Optional[ServiceEndpoint]:
        with self._lock:
            for ep in self._endpoints.values():
                if ep.name == name:
                    return ep
            return None

    def list_endpoints(self, environment: Optional[str] = None, type: Optional[str] = None) -> List[ServiceEndpoint]:
        with self._lock:
            endpoints = list(self._endpoints.values())
            if environment:
                endpoints = [e for e in endpoints if environment in e.environments]
            if type:
                endpoints = [e for e in endpoints if e.type == type]
            return endpoints

    def update_endpoint(self, endpoint_id: str, updates: Dict[str, Any]) -> Optional[ServiceEndpoint]:
        with self._lock:
            endpoint = self._endpoints.get(endpoint_id)
            if not endpoint:
                return None
            for key, value in updates.items():
                if key == 'method':
                    endpoint.method = DistributionMethod(value)
                elif hasattr(endpoint, key):
                    setattr(endpoint, key, value)
            endpoint.updated_at = datetime.now(timezone.utc).isoformat()
            self._save_endpoints()
            return endpoint

    def delete_endpoint(self, endpoint_id: str) -> bool:
        with self._lock:
            if endpoint_id not in self._endpoints:
                return False
            del self._endpoints[endpoint_id]
            self._save_endpoints()
            return True

    def create_distribution(
        self,
        environment_id: str,
        environment_name: str,
        configs: Dict[str, Any],
        version: int,
        targets: List[str],
        triggered_by: str = "system",
        metadata: Dict[str, Any] = None
    ) -> ConfigDistribution:
        with self._lock:
            # Compute checksum
            config_str = json.dumps(configs, sort_keys=True)
            checksum = hashlib.sha256(config_str.encode()).hexdigest()[:32]
            
            distribution = ConfigDistribution(
                id=str(uuid.uuid4()),
                environment_id=environment_id,
                environment_name=environment_name,
                configs=configs,
                version=version,
                status=DistributionStatus.PENDING,
                targets=targets,
                checksum=checksum,
                triggered_by=triggered_by,
                metadata=metadata or {}
            )
            self._distributions[distribution.id] = distribution
            self._save_distributions()
            return distribution

    def get_distribution(self, distribution_id: str) -> Optional[ConfigDistribution]:
        with self._lock:
            return self._distributions.get(distribution_id)

    def list_distributions(self, environment_id: Optional[str] = None, limit: int = 50) -> List[ConfigDistribution]:
        with self._lock:
            distributions = list(self._distributions.values())
            if environment_id:
                distributions = [d for d in distributions if d.environment_id == environment_id]
            distributions.sort(key=lambda d: d.started_at or '', reverse=True)
            return distributions[:limit]

    def update_distribution(self, distribution_id: str, updates: Dict[str, Any]) -> Optional[ConfigDistribution]:
        with self._lock:
            distribution = self._distributions.get(distribution_id)
            if not distribution:
                return None
            for key, value in updates.items():
                if key == 'status':
                    distribution.status = DistributionStatus(value)
                elif hasattr(distribution, key):
                    setattr(distribution, key, value)
            self._save_distributions()
            return distribution

    def add_result(self, distribution_id: str, result: DistributionResult):
        with self._lock:
            distribution = self._distributions.get(distribution_id)
            if distribution:
                distribution.results[result.endpoint_id] = asdict(result)
                self._save_distributions()


class DistributionEngine:
    """Engine for distributing configurations to service endpoints."""
    
    def __init__(
        self,
        store: DistributionStore,
        env_store: Optional['EnvironmentStore'] = None,
        http_client: Optional[Callable] = None
    ):
        self.store = store
        self.env_store = env_store
        self._http_client = http_client or self._default_http_client
        self._running = False
        self._thread = None

    def _default_http_client(self, method: str, url: str, **kwargs) -> Dict[str, Any]:
        """Default HTTP client using urllib."""
        import urllib.request
        import urllib.error
        
        req = urllib.request.Request(url, method=method)
        for key, value in kwargs.get('headers', {}).items():
            req.add_header(key, value)
        if 'json' in kwargs:
            req.add_header('Content-Type', 'application/json')
            data = json.dumps(kwargs['json']).encode('utf-8')
        else:
            data = kwargs.get('data')
        
        try:
            with urllib.request.urlopen(req, data=data, timeout=kwargs.get('timeout', 30)) as resp:
                return {
                    'status': resp.status,
                    'body': json.loads(resp.read().decode('utf-8')) if resp.length else {}
                }
        except urllib.error.HTTPError as e:
            return {
                'status': e.code,
                'error': e.read().decode('utf-8') if e.length else str(e)
            }
        except Exception as e:
            return {
                'status': 0,
                'error': str(e)
            }

    def distribute(self, distribution_id: str) -> Dict[str, Any]:
        """Execute a configuration distribution."""
        distribution = self.store.get_distribution(distribution_id)
        if not distribution:
            return {"success": False, "error": "Distribution not found"}
        
        if distribution.status != DistributionStatus.PENDING:
            return {"success": False, "error": f"Distribution already {distribution.status.value}"}
        
        # Update status
        distribution.status = DistributionStatus.IN_PROGRESS
        distribution.started_at = datetime.now(timezone.utc).isoformat()
        self.store.update_distribution(distribution_id, {
            'status': distribution.status,
            'started_at': distribution.started_at
        })
        
        results = {}
        all_success = True
        
        for endpoint_id in distribution.targets:
            endpoint = self.store.get_endpoint(endpoint_id)
            if not endpoint:
                result = DistributionResult(
                    distribution_id=distribution_id,
                    endpoint_id=endpoint_id,
                    endpoint_name="unknown",
                    success=False,
                    error="Endpoint not found"
                )
                results[endpoint_id] = asdict(result)
                all_success = False
                continue
            
            # Check if endpoint targets this environment
            if endpoint.environments and distribution.environment_name not in endpoint.environments:
                result = DistributionResult(
                    distribution_id=distribution_id,
                    endpoint_id=endpoint_id,
                    endpoint_name=endpoint.name,
                    success=True,
                    error="Skipped: environment not targeted"
                )
                results[endpoint_id] = asdict(result)
                continue
            
            result = self._distribute_to_endpoint(distribution, endpoint)
            results[endpoint_id] = asdict(result)
            self.store.add_result(distribution_id, result)
            
            if not result.success:
                all_success = False
        
        # Update final status
        distribution.status = DistributionStatus.COMPLETED if all_success else DistributionStatus.FAILED
        distribution.completed_at = datetime.now(timezone.utc).isoformat()
        self.store.update_distribution(distribution_id, {
            'status': distribution.status,
            'completed_at': distribution.completed_at
        })
        
        return {
            "success": all_success,
            "distribution_id": distribution_id,
            "results": results
        }

    def _distribute_to_endpoint(self, distribution: ConfigDistribution, endpoint: ServiceEndpoint) -> DistributionResult:
        """Distribute config to a single endpoint."""
        start_time = time.time()
        url = f"{endpoint.base_url.rstrip('/')}{endpoint.config_endpoint}"
        
        payload = {
            "environment": distribution.environment_name,
            "version": distribution.version,
            "checksum": distribution.checksum,
            "configs": distribution.configs,
            "metadata": distribution.metadata
        }
        
        headers = {
            'Content-Type': 'application/json',
            'X-Config-Version': str(distribution.version),
            'X-Config-Checksum': distribution.checksum,
            **endpoint.headers
        }
        
        last_error = None
        for attempt in range(endpoint.retry_count):
            try:
                resp = self._http_client('POST', url, json=payload, headers=headers, timeout=endpoint.timeout_seconds)
                duration_ms = (time.time() - start_time) * 1000
                
                if resp.get('status', 0) in (200, 201, 202):
                    return DistributionResult(
                        distribution_id=distribution.id,
                        endpoint_id=endpoint.id,
                        endpoint_name=endpoint.name,
                        success=True,
                        status_code=resp.get('status'),
                        response=resp.get('body'),
                        duration_ms=duration_ms
                    )
                else:
                    last_error = f"HTTP {resp.get('status')}: {resp.get('error', 'Unknown error')}"
            except Exception as e:
                last_error = str(e)
            
            if attempt < endpoint.retry_count - 1:
                time.sleep(endpoint.retry_delay_seconds)
        
        duration_ms = (time.time() - start_time) * 1000
        return DistributionResult(
            distribution_id=distribution.id,
            endpoint_id=endpoint.id,
            endpoint_name=endpoint.name,
            success=False,
            error=last_error,
            duration_ms=duration_ms
        )

    def rollback_distribution(self, distribution_id: str, rollback_version: int) -> Dict[str, Any]:
        """Rollback a distribution to a previous version."""
        distribution = self.store.get_distribution(distribution_id)
        if not distribution:
            return {"success": False, "error": "Distribution not found"}
        
        if not self.env_store:
            return {"success": False, "error": "Environment store not available"}
        
        # Get target environment
        env = self.env_store.get_environment(distribution.environment_id)
        if not env:
            return {"success": False, "error": "Environment not found"}
        
        # Rollback environment
        success = self.env_store.rollback(env.id, rollback_version)
        if not success:
            return {"success": False, "error": f"Rollback to version {rollback_version} failed"}
        
        # Create new distribution with rolled back configs
        new_dist = self.store.create_distribution(
            environment_id=distribution.environment_id,
            environment_name=distribution.environment_name,
            configs=env.configs,
            version=env.version,
            targets=distribution.targets,
            triggered_by="rollback",
            metadata={"rollback_from": distribution.id, "rollback_version": rollback_version}
        )
        
        # Execute rollback distribution
        result = self.distribute(new_dist.id)
        if result['success']:
            self.store.update_distribution(distribution_id, {'status': DistributionStatus.ROLLED_BACK.value})
        
        return result


# Default service endpoints for the ecosystem
def register_default_endpoints(store: DistributionStore) -> List[ServiceEndpoint]:
    """Register default ecosystem service endpoints."""
    endpoints = []
    
    rlm_services = [
        ("RLM-243", "http://127.0.0.1:8080", "rlm", ["development", "staging", "production"]),
        ("RLM-CONFIG", "http://127.0.0.1:8794", "rlm", ["development", "staging", "production"]),
        ("RLM-GRAPH", "http://127.0.0.1:8797", "rlm", ["development", "staging", "production"]),
        ("RLM-DEPLOY", "http://127.0.0.1:8795", "rlm", ["development", "staging", "production"]),
        ("RLM-SECURE", "http://127.0.0.1:8796", "rlm", ["development", "staging", "production"]),
        ("RLM-INCIDENT", "http://127.0.0.1:8798", "rlm", ["development", "staging", "production"]),
        ("RLM-RELEASE", "http://127.0.0.1:8799", "rlm", ["development", "staging", "production"]),
        ("RLM-MDU", "http://127.0.0.1:8793", "rlm", ["development", "staging", "production"]),
        ("KIX", "http://127.0.0.1:8800", "orchestrator", ["development", "staging", "production"]),
        ("MIMIR", "http://127.0.0.1:8000", "monitoring", ["development", "staging", "production"]),
    ]
    
    for name, url, ep_type, envs in rlm_services:
        endpoint = ServiceEndpoint(
            id=str(uuid.uuid4()),
            name=name,
            type=ep_type,
            base_url=url,
            health_endpoint="/health",
            config_endpoint="/config",
            method=DistributionMethod.PUSH,
            environments=envs,
            headers={"X-Source": "RLM-CONFIG"},
            metadata={"description": f"{name} runner service"}
        )
        try:
            store.register_endpoint(endpoint)
            endpoints.append(endpoint)
        except ValueError:
            existing = store.get_endpoint_by_name(name)
            if existing:
                endpoints.append(existing)
    
    return endpoints