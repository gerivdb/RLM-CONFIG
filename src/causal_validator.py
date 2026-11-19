"""
RLM-CONFIG causal_validator - Composant auto-dev integre.

Contexte:
- RLM-CONFIG est un composant de l'ecosysteme gerivdb.
- causal_validator permet de valider la cohérence causale via ROOTX.

Integration:
- GOVERNANCE-HUB: SOT, ADR, PRD-MOC, hooks
- KG-L / VERSES: connaissances et ontologie
- ROOTX: racines de connaissances (http://localhost:8030)
- RLM-CONFIG: composant hote
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class CausalValidatorConfig:
    """Configuration du composant causal_validator."""

    rootx_endpoint: str = "http://localhost:8030"
    timeout_seconds: int = 5


class CausalValidator:
    """Composant causal_validator - valide les chemins causaux via ROOTX."""

    def __init__(self, config: CausalValidatorConfig | None = None) -> None:
        self.config = config or CausalValidatorConfig()

    def health(self) -> dict[str, Any]:
        """Verifie la disponibilite du composant et de ROOTX."""
        try:
            req = urllib.request.Request(
                f"{self.config.rootx_endpoint}/health",
                method="GET",
            )
            with urllib.request.urlopen(
                req, timeout=self.config.timeout_seconds
            ) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return {
                    "status": "ok",
                    "service": "rlm-config",
                    "rootx": body,
                }
        except Exception as exc:
            return {
                "status": "degraded",
                "service": "rlm-config",
                "rootx_error": str(exc),
            }

    def validate_causal(self, service: str) -> dict[str, Any]:
        """Valide un chemin causal pour un service donne via ROOTX.

        Retourne un dict au format {valid: bool, confidence: float, errors: []}.
        """
        payload = {
            "service": service,
            "action": "validate",
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.config.rootx_endpoint}/validate",
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
                    "valid": body.get("valid", False),
                    "confidence": body.get("confidence", 0.0),
                    "errors": body.get("errors", []),
                }
        except urllib.error.HTTPError as exc:
            return {
                "valid": False,
                "confidence": 0.0,
                "errors": [f"HTTP {exc.code}: {exc.reason}"],
            }
        except Exception as exc:
            return {
                "valid": False,
                "confidence": 0.0,
                "errors": [str(exc)],
            }


def build_causal_validator(
    config: CausalValidatorConfig | None = None,
) -> CausalValidator:
    """Factory pour creer une instance de CausalValidator."""
    return CausalValidator(config=config)
