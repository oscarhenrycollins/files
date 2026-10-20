"""Packaging contract; run with python -m unittest discover -s tests (PyYAML)."""
import json
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class SameOrigin(unittest.TestCase):
    def test_view_and_engine_share_prefix(self):
        meta = yaml.safe_load((ROOT / 'wizard.md').read_text().split('---')[1])
        recipe = yaml.safe_load((ROOT / 'runtipi/docker-compose.yml').read_text())
        engine = recipe['services']['files-engine']
        self.assertEqual(meta['view']['path'], '/files/')
        self.assertEqual(engine['environment']['FB_BASEURL'], '/files')
        self.assertIn('http://127.0.0.1:8080/files/health', engine['healthcheck']['test'])
        self.assertEqual(meta['mcp']['path'], '/mcp')
        cfg = json.loads((ROOT / 'runtipi/config.json').read_text())
        self.assertEqual(cfg['version'], 'v' + meta['version'])
        self.assertEqual(recipe['services']['files']['environment']['APP_VERSION'], meta['version'])

    def test_prefix_override_preserves_owner_database(self):
        recipe = yaml.safe_load((ROOT / 'runtipi/docker-compose.yml').read_text())
        engine = recipe['services']['files-engine']
        self.assertIn('${APP_DATA_DIR}/data/db:/database', engine['volumes'])
        script = engine['entrypoint'][-1]
        self.assertIn('if [ ! -f "$$DB" ]; then', script)
        self.assertNotIn('rm ', script)
        self.assertNotIn('chown -R', script)
        self.assertNotIn('chmod -R', script)


if __name__ == '__main__':
    unittest.main()
