"""
RLM-GRAPH meta_coherence_fixer - Client fonctionnel pour le méta-orchestrateur N243.

Contexte:
- RLM-GRAPH est un composant de l'ecosysteme gerivdb.
- meta_coherence_fixer interroge le service N243 pour valider et corriger la cohérence
  métalogique des composants.

Integration:
- GOVERNANCE-HUB: SOT, ADR, PRD-MOC, hooks
- KG-L / VERSES: connaissances et ontologie
- N243: méta-orchestrateur de validation de cohérence (http://localhost:8050)
- RLM-GRAPH: composant hote
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class MetaCoherenceFixerConfig:
    """Configuration du composant meta_coherence_fixer."""

    def __init__(self, endpoint: str = "http://localhost:8050", timeout_seconds: int = 10):
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds


class MetaCoherenceFixer:
    """Client fonctionnel pour interroger le méta-orchestrateur N243."""

    def __init__(self, config: MetaCoherenceFixerConfig | None = None) -> None:
        self.config = config or MetaCoherenceFixerConfig()

    def health(self) -> dict[str, Any]:
        """Verifie la disponibilite du service N243."""
        try:
            req = urllib.request.Request(f"{self.config.endpoint}/health", method="GET")
            with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as e:
            return {"status": "degraded", "error": str(e), "endpoint": self.config.endpoint}

    def fix_coherence(self, data: dict[str, Any]) -> dict[str, Any]:
        """Valide et corrige la cohérence métalogique via N243.

        Retourne un dict avec les champs {coherent, fixes_applied, confidence},
        ou un dict d'erreur degrade en cas d'echec.
        """
        try:
            req = urllib.request.Request(
                f"{self.config.endpoint}/fix",
                data=json.dumps(data).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return {"coherent": False, "fixes_applied": 0, "confidence": 0.0, "error": f"HTTP Error {e.code}"}
        except urllib.error.URLError as e:
            return {"coherent": False, "fixes_applied": 0, "confidence": 0.0, "error": f"Connection refused: {e.reason}"}
        except Exception as e:
            return {"coherent": False, "fixes_applied": 0, "confidence": 0.0, "error": f"Unexpected error: {str(e)}"}


def build_meta_coherence_fixer(
    endpoint: str = "http://localhost:8050", timeout_seconds: int = 10
) -> MetaCoherenceFixer:
    """Factory pour creer une instance de MetaCoherenceFixer."""
    return MetaCoherenceFixer(MetaCoherenceFixerConfig(endpoint, timeout_seconds))
