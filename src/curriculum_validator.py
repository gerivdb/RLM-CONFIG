"""
RLM-GRAPH curriculum_validator - Client fonctionnel pour le moteur CURX.

Contexte:
- RLM-GRAPH est un composant de l'ecosysteme gerivdb.
- curriculum_validator interroge le moteur CURX pour valider les curriculums.

Integration:
- GOVERNANCE-HUB: SOT, ADR, PRD-MOC, hooks
- KG-L / VERSES: connaissances et ontologie
- CURX: moteur de validation curriculum (http://localhost:8040)
- RLM-GRAPH: composant hote
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class CurriculumValidatorConfig:
    """Configuration du composant curriculum_validator."""

    def __init__(self, endpoint: str = "http://localhost:8040", timeout_seconds: int = 10):
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds


class CurriculumValidator:
    """Client fonctionnel pour interroger le moteur CURX."""

    def __init__(self, config: CurriculumValidatorConfig | None = None) -> None:
        self.config = config or CurriculumValidatorConfig()

    def health(self) -> dict[str, Any]:
        """Verifie la disponibilite du service CURX."""
        try:
            req = urllib.request.Request(f"{self.config.endpoint}/health", method="GET")
            with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as e:
            return {"status": "degraded", "error": str(e), "endpoint": self.config.endpoint}

    def validate_curriculum(self, data: dict[str, Any]) -> dict[str, Any]:
        """Valide un curriculum via CURX.

        Retourne un dict avec les champs retournes par CURX,
        ou un dict d'erreur degrade en cas d'echec.
        """
        try:
            req = urllib.request.Request(
                f"{self.config.endpoint}/validate",
                data=json.dumps(data).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return {"valid": False, "confidence": 0.0, "feedback": [f"HTTP Error {e.code}"]}
        except urllib.error.URLError as e:
            return {"valid": False, "confidence": 0.0, "feedback": [f"Connection refused: {e.reason}"]}
        except OSError as e:
            return {"valid": False, "confidence": 0.0, "feedback": [f"Connection refused: {e.reason}"]}
        except Exception as e:
            return {"valid": False, "confidence": 0.0, "feedback": [f"Unexpected error: {str(e)}"]}


def build_curriculum_validator(endpoint: str = "http://localhost:8040", timeout_seconds: int = 10) -> CurriculumValidator:
    """Factory pour creer une instance de CurriculumValidator."""
    return CurriculumValidator(CurriculumValidatorConfig(endpoint, timeout_seconds))
