"""Check entry points and import boundaries after reorganizing the repository."""

import importlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


class StructureTest(unittest.TestCase):
    def test_api_entrypoint(self):
        config = json.loads((ROOT / "aegra.json").read_text())
        path, symbol = config["graphs"]["agent"].split(":")
        self.assertTrue((ROOT / path).is_file())
        module = importlib.import_module("preptalk.api.graph")
        self.assertTrue(callable(getattr(module, symbol).invoke))

    def test_evaluation_imports_do_not_call_models(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("network call during import")):
            for path in (ROOT / "evaluation").glob("*.py"):
                if path.stem != "__init__":
                    with self.subTest(module=path.stem):
                        importlib.import_module(f"evaluation.{path.stem}")


if __name__ == "__main__":
    unittest.main()
