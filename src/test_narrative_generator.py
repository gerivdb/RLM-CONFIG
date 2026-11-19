#!/usr/bin/env python3
"""Script de test d'intégration pour narrative_generator (RLM-CONFIG).

Valide les 3 scénarios critiques :
1. Succès du health check
2. Flux nominal de génération narrative
3. Résilience face à un serveur injoignable

Technologie : unittest + urllib (stdlib uniquement, ZCF-0.0).
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from narrative_generator import build_narrative_generator, NarrativeGeneratorConfig


class TestNarrativeGeneratorIntegration(unittest.TestCase):

    def setUp(self):
        # Pointe vers le moteur narratif TALEX actif sur le port 8060
        self.client = build_narrative_generator(endpoint="http://localhost:8060", timeout_seconds=5)

    def test_health_ok(self):
        """Teste que le serveur MVP TALEX répond correctement au health check."""
        result = self.client.health()
        self.assertEqual(result.get("status"), "ok")

    def test_generate_narrative_success(self):
        """Teste le flux nominal de génération narrative."""
        payload = {"topic": "test-topic"}
        result = self.client.generate_narrative(payload)

        self.assertIsInstance(result.get("narrative"), str)
        self.assertGreaterEqual(result.get("confidence", 0), 0.80)
        self.assertIsInstance(result.get("metadata"), dict)

    def test_generate_narrative_connection_refused(self):
        """Teste la résilience face à un serveur injoignable (port faux)."""
        bad_client = build_narrative_generator(endpoint="http://localhost:9999", timeout_seconds=2)
        result = bad_client.generate_narrative({"topic": "test-topic"})

        self.assertEqual(result.get("narrative"), "")
        self.assertIn("error", result)

if __name__ == '__main__':
    unittest.main(verbosity=2)
