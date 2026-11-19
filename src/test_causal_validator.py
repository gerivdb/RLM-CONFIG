#!/usr/bin/env python3
"""Script de test d'intégration pour causal_validator (ROOTX MVP) — RLM-CONFIG.

Valide les 3 scénarios critiques :
1. Succès du health check
2. Flux nominal de validation causale
3. Résilience face à un serveur injoignable

Technologie : unittest + urllib (stdlib uniquement, ZCF-0.0).
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from causal_validator import build_causal_validator, CausalValidatorConfig


class TestCausalValidatorIntegration(unittest.TestCase):

    def setUp(self):
        config = CausalValidatorConfig(rootx_endpoint="http://localhost:8030", timeout_seconds=5)
        self.client = build_causal_validator(config=config)

    def test_health_ok(self):
        """Le serveur MVP ROOTX répond correctement au health check."""
        result = self.client.health()
        self.assertEqual(result.get("status"), "ok")

    def test_validate_causal_success(self):
        """Le flux nominal de validation causale retourne valid=True."""
        result = self.client.validate_causal("test-service")
        self.assertTrue(result.get("valid"))
        self.assertGreaterEqual(result.get("confidence", 0), 0.90)
        self.assertIsInstance(result.get("errors"), list)

    def test_validate_causal_connection_refused(self):
        """Un serveur injoignable retourne un échec gracieux sans exception."""
        config = CausalValidatorConfig(rootx_endpoint="http://localhost:9999", timeout_seconds=2)
        bad_client = build_causal_validator(config=config)
        result = bad_client.validate_causal("test-service")
        self.assertFalse(result.get("valid", True))
        self.assertIn("errors", result)


if __name__ == '__main__':
    unittest.main(verbosity=2)
