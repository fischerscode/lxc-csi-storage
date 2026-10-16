"""Lock validation rejects path injection and incomplete/ambiguous inputs."""
from pathlib import Path
import tempfile
import unittest

import fixtures  # Adds the repository scripts directory to the import path.
from package_lock import locked


class PackageLockTests(unittest.TestCase):
    def test_actual_lock_has_runtime_and_build_closures(self):
        packages = locked()
        self.assertEqual(packages['gcompat'][0], '1.1.0-r4')
        self.assertEqual(packages['gcompat'][3], 'runtime')
        self.assertEqual(packages['npm'][3], 'build')

    def test_rejects_invalid_and_duplicate_records(self):
        digest = 'a' * 64
        valid = f'{digest} main/example-1.0-r0.apk runtime\n'
        for text in ('', valid * 2, valid.replace('main/', '../'),
                     valid.replace('1.0-r0', '1/../../escape-r0'),
                     valid.replace('runtime', 'unknown'),
                     valid.replace(digest, 'incorrect-hash')):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'packages.lock'
                path.write_text(text)
                with self.assertRaises(ValueError):
                    locked(path)
