"""Exercise the release verifier through its compressed archive CLI."""
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

from test_policy import clean

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('zstd'), 'zstd is required for archive tests')
class ArchiveTests(unittest.TestCase):
    def test_compressed_contract_and_truncated_stream(self):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w') as archive:
            for name, kind, link, data in clean():
                entry = tarfile.TarInfo(name)
                if kind == 'symlink':
                    entry.type = tarfile.SYMTYPE
                    entry.linkname = link
                    archive.addfile(entry)
                else:
                    entry.size = len(data)
                    archive.addfile(entry, io.BytesIO(data))
        packed = subprocess.run(['zstd', '-q', '-c'], input=stream.getvalue(),
                                stdout=subprocess.PIPE, check=True).stdout
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.tar.zst'
            path.write_bytes(packed)
            command = [sys.executable, '-B', str(ROOT / 'scripts/verify.py'),
                       '--archive', str(path)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Clean template verified: v0.0.0-test', result.stdout)
            path.write_bytes(packed[:-8])
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
