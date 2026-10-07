"""Reject stale local assets that leave Lyne controls unregistered."""
import json
import sys
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ui import lyne


class LyneAssetsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vendor = self.root / "vendor"
        self.vendor.mkdir()
        for name in ("sbb-elements.bundle.js", "sbb-variables.css", "standard-theme.css"):
            (self.vendor / name).write_text("test asset")
        patcher = patch.object(lyne, "static_root", return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.manifest = {
            "elements_version": lyne.LYNE_ELEMENTS_VERSION,
            "tokens_version": lyne.LYNE_DESIGN_TOKENS_VERSION,
            "components": list(lyne.LYNE_COMPONENT_MODULES),
            "bundle_sha256": sha256(b"test asset").hexdigest(),
        }

    def write_manifest(self):
        (self.vendor / "manifest.json").write_text(json.dumps(self.manifest))

    def test_legacy_bundle_falls_back_to_complete_component_imports(self):
        html = lyne.lyne_assets()
        self.assertNotIn("/static/vendor/", html)
        for component in ("checkbox", "radio-button", "radio-button-group"):
            self.assertIn(f"/{component}.js/+esm", html)

    def test_current_bundle_is_served_locally(self):
        self.write_manifest()
        html = lyne.lyne_assets()
        self.assertIn("/static/vendor/sbb-elements.bundle.js?v=", html)
        self.assertNotIn(lyne.JSDELIVR_NPM, html)

    def test_missing_component_is_rejected(self):
        self.manifest["components"].remove("checkbox")
        self.write_manifest()
        self.assertFalse(lyne.has_vendored_lyne())

    def test_changed_bundle_is_rejected(self):
        self.write_manifest()
        (self.vendor / "sbb-elements.bundle.js").write_text("old bundle")
        self.assertFalse(lyne.has_vendored_lyne())

    def test_old_package_version_is_rejected(self):
        self.manifest["elements_version"] = "0.0.0"
        self.write_manifest()
        self.assertFalse(lyne.has_vendored_lyne())

    def test_invalid_manifest_is_rejected(self):
        for content in ("{", "null", "[]", '{"components": [null, {}]}'):
            with self.subTest(content=content):
                (self.vendor / "manifest.json").write_text(content)
                self.assertFalse(lyne.has_vendored_lyne())


if __name__ == "__main__":
    unittest.main()
