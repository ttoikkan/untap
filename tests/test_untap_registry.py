import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from untap_registry import register_run
from untap_snapshot import build_snapshot, save_snapshot


class RegistryTests(unittest.TestCase):
    def test_new_menu_and_existing_entry_preserved(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            run = root / "run"
            run.mkdir()
            save_snapshot(build_snapshot([], "Menu"), run / "results.json")
            config = root / "refresh.json"
            self.assertTrue(register_run(config, run))
            data = json.loads(config.read_text())
            data["defaults"] = {"archive": "../archive", "replace": True}
            self.assertEqual(data["reports"][0]["source"], "run")
            data["reports"][0].update(archive="../archive", selections="choices.json", replace=True)
            config.write_text(json.dumps(data))
            before = config.read_bytes()
            self.assertFalse(register_run(config, run))
            self.assertEqual(config.read_bytes(), before)

    def test_invalid_configuration_is_not_modified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_snapshot(build_snapshot([], "Menu"), root / "results.json")
            config = root / "refresh.json"
            config.write_text("invalid")
            with self.assertRaises(ValueError):
                register_run(config, root)
            self.assertEqual(config.read_text(), "invalid")
