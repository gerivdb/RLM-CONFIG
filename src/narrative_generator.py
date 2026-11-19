"""
RLM-GRAPH narrative_generator - Client fonctionnel pour le moteur narratif TALEX.

Contexte:
- RLM-GRAPH est un composant de l'ecosysteme gerivdb.
- narrative_generator interroge le moteur TALEX pour generer des narrations
  a partir de donnees structurees.

Integration:
- GOVERNANCE-HUB: SOT, ADR, PRD-MOC, hooks
- KG-L / VERSES: connaissances et ontologie
- TALEX: moteur narratif (http://localhost:8060)
- RLM-GRAPH: composant hote
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class NarrativeGeneratorConfig:
    """Configuration du composant narrative_generator."""

    def __init__(self, endpoint: str = "http://localhost:8060", timeout_seconds: int = 10):
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds


class NarrativeGenerator:
    """Client fonctionnel pour interroger le moteur narratif TALEX."""

    def __init__(self, config: NarrativeGeneratorConfig | None = None) -> None:
        self.config = config or NarrativeGeneratorConfig()

    def health(self) -> dict[str, Any]:
        """Verifie la disponibilite du service TALEX."""
        try:
            req = urllib.request.Request(f"{self.config.endpoint}/health", method="GET")
            with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as e:
            return {"status": "degraded", "error": str(e), "endpoint": self.config.endpoint}

    def generate_narrative(self, data: dict[str, Any]) -> dict[str, Any]:
        """Genere une narration via TALEX.

        Retourne un dict avec les champs {narrative, metadata, confidence},
        ou un dict d'erreur degrade en cas d'echec.
        """
        try:
            req = urllib.request.Request(
                f"{self.config.endpoint}/generate",
                data=json.dumps(data).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return {"narrative": "", "metadata": {}, "confidence": 0.0, "error": f"HTTP Error {e.code}"}
        except urllib.error.URLError as e:
            return {"narrative": "", "metadata": {}, "confidence": 0.0, "error": f"Connection refused: {e.reason}"}
        except Exception as e:
            return {"narrative": "", "metadata": {}, "confidence": 0.0, "error": f"Unexpected error: {str(e)}"}


def build_narrative_generator(
    endpoint: str = "http://localhost:8060", timeout_seconds: int = 10
) -> NarrativeGenerator:
    """Factory pour creer une instance de NarrativeGenerator."""
    return NarrativeGenerator(NarrativeGeneratorConfig(endpoint, timeout_seconds))
