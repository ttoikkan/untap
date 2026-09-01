from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent


class ReproducibleEnvironmentTests(unittest.TestCase):
    def test_playwright_runtime_dependency_is_exactly_pinned(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        active = [
            line.strip()
            for line in requirements.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(active, ["playwright==1.57.0"])



if __name__ == "__main__":
    unittest.main()
