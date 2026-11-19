"""
RLM-GRAPH rootx_client - Client fonctionnel pour interroger ROOTX.

Contexte:
- RLM-GRAPH est un composant de l'ecosysteme gerivdb.
- rootx_client permet la connexion et l'interrogation des racines de connaissances (ROOTX).

Integration:
- GOVERNANCE-HUB: SOT, ADR, PRD-MOC, hooks
- KG-L / VERSES: connaissances et ontologie
- ROOTX: racines de connaissances (http://localhost:8030)
- RLM-GRAPH: composant hote
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class RootxClientConfig:
    """Configuration du composant rootx_client."""

    endpoint: str = "http://localhost:8030"
    timeout_seconds: int = 5


class RootxClient:
    """Client fonctionnel pour interroger les racines ROOTX."""

    def __init__(self, config: RootxClientConfig | None = None) -> None:
        self.config = config or RootxClientConfig()

    def health(self) -> dict[str, Any]:
        """Verifie la disponibilite du service ROOTX."""
        try:
            req = urllib.request.Request(
                f"{self.config.endpoint}/health",
                method="GET",
            )
            with urllib.request.urlopen(
                req, timeout=self.config.timeout_seconds
            ) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return {
                    "status": "ok",
                    "service": "rlm-graph",
                    "rootx": body,
                }
        except Exception as exc:
            return {
                "status": "degraded",
                "service": "rlm-graph",
                "rootx_error": str(exc),
            }

    def query(self, root_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Interroge une racine ROOTX via l'endpoint /validate.

        Retourne un dict avec les champs {valid, confidence, errors},
        ou un dict d'erreur en cas d'echec.
        """
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.config.endpoint}/validate",
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(
                req, timeout=self.config.timeout_seconds
            ) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return {
                    "root_id": root_id,
                    "valid": body.get("valid", False),
                    "confidence": body.get("confidence", 0.0),
                    "errors": body.get("errors", []),
                }
        except urllib.error.HTTPError as exc:
            return {
                "root_id": root_id,
                "valid": False,
                "confidence": 0.0,
                "errors": [f"HTTP {exc.code}: {exc.reason}"],
            }
        except Exception as exc:
            return {
                "root_id": root_id,
                "valid": False,
                "confidence": 0.0,
                "errors": [str(exc)],
            }


def build_rootx_client(config: RootxClientConfig | None = None) -> RootxClient:
    """Factory pour creer une instance de RootxClient."""
    return RootxClient(config=config)
