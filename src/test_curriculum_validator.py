#!/usr/bin/env python3
"""Script de test d'intégration pour curriculum_validator (RLM-CONFIG).

Valide les 3 scénarios critiques :
1. Succès du health check
2. Flux nominal de validation curriculum
3. Résilience face à un serveur injoignable

Technologie : unittest + urllib (stdlib uniquement, ZCF-0.0).
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from curriculum_validator import build_curriculum_validator, CurriculumValidatorConfig


class TestCurriculumValidatorIntegration(unittest.TestCase):

    def setUp(self):
        # Pointe vers le serveur MVP CURX actif sur le port 8040
        self.client = build_curriculum_validator(endpoint="http://localhost:8040", timeout_seconds=5)

    def test_health_ok(self):
        """Teste que le serveur MVP CURX répond correctement au health check."""
        result = self.client.health()
        self.assertEqual(result.get("status"), "ok")

    def test_validate_curriculum_success(self):
        """Teste le flux nominal de validation curriculum."""
        payload = {"service": "test-service"}
        result = self.client.validate_curriculum(payload)

        self.assertTrue(result.get("valid"))
        self.assertGreaterEqual(result.get("confidence", 0), 0.90)
        self.assertIsInstance(result.get("feedback"), list)

    def test_validate_curriculum_connection_refused(self):
        """Teste la résilience face à un serveur injoignable (port faux)."""
        bad_client = build_curriculum_validator(endpoint="http://localhost:9999", timeout_seconds=2)
        result = bad_client.validate_curriculum({"service": "test-service"})

        self.assertFalse(result.get("valid", True))
        self.assertIn("feedback", result)

if __name__ == '__main__':
    unittest.main(verbosity=2)
