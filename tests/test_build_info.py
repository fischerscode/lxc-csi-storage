"""Build provenance binds all builder inputs without disclosing runner state."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_info', ROOT / 'scripts/build_info.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BuildInfoTests(unittest.TestCase):
    def test_public_inputs_and_dirty_state(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / 'scripts').mkdir()
            (repo / 'build-config.json').write_text('{"schema_version": 1}')
            builder = repo / 'scripts/build.sh'
            builder.write_text('public build input\n')
            (repo / 'scripts/finalize.py').write_text('public finalizer\n')
            # Neither a local identity nor unrelated runtime files are captured.
            (repo / 'private-local-file').write_text('not a build input')

            def command(*args):
                if args[:2] == ('git', 'rev-parse'):
                    return 'a' * 40
                if args[:2] == ('git', 'log'):
                    return '1792152000'
                if args[:2] == ('git', 'status'):
                    return ' M scripts/build.sh'
                return 'public tool version\nadditional line'

            with patch.object(module, 'REPO', repo), patch.object(module, 'command', command):
                info = module.build_info('v0.1.0-test')
                self.assertFalse(info['working_tree_clean'])
                self.assertEqual(info['source_commit'], 'a' * 40)
                self.assertEqual(info['source_date_epoch'], 1792152000)
                self.assertEqual(info['inputs_sha256']['scripts/build.sh'],
                                 hashlib.sha256(builder.read_bytes()).hexdigest())
                self.assertEqual(set(info['inputs_sha256']),
                                 {'build-config.json', 'scripts/build.sh', 'scripts/finalize.py'})
                self.assertNotIn(directory, str(info))
                self.assertNotIn('not a build input', str(info))
                builder.write_text('changed public build input\n')
                self.assertNotEqual(info['inputs_sha256'],
                                    module.build_info('v0.1.0-test')['inputs_sha256'])
