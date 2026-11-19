#!/usr/bin/env python3
"""Script de test d'intégration pour meta_coherence_fixer (RLM-CONFIG).

Valide les 3 scénarios critiques :
1. Succès du health check
2. Flux nominal de correction de cohérence
3. Résilience face à un serveur injoignable

Technologie : unittest + urllib (stdlib uniquement, ZCF-0.0).
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from meta_coherence_fixer import build_meta_coherence_fixer, MetaCoherenceFixerConfig


class TestMetaCoherenceFixerIntegration(unittest.TestCase):

    def setUp(self):
        # Pointe vers le méta-orchestrateur N243 actif sur le port 8050
        self.client = build_meta_coherence_fixer(endpoint="http://localhost:8050", timeout_seconds=5)

    def test_health_ok(self):
        """Teste que le serveur MVP N243 répond correctement au health check."""
        result = self.client.health()
        self.assertEqual(result.get("status"), "ok")

    def test_fix_coherence_success(self):
        """Teste le flux nominal de correction de cohérence."""
        payload = {"component": "test-component"}
        result = self.client.fix_coherence(payload)

        self.assertTrue(result.get("coherent"))
        self.assertGreaterEqual(result.get("confidence", 0), 0.80)
        self.assertIsInstance(result.get("fixes_applied"), int)

    def test_fix_coherence_connection_refused(self):
        """Teste la résilience face à un serveur injoignable (port faux)."""
        bad_client = build_meta_coherence_fixer(endpoint="http://localhost:9999", timeout_seconds=2)
        result = bad_client.fix_coherence({"component": "test-component"})

        self.assertFalse(result.get("coherent", True))
        self.assertIn("error", result)

if __name__ == '__main__':
    unittest.main(verbosity=2)
