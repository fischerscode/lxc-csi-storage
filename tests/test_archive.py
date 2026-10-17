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
from application_permissions import DRIVER, DRIVER_DIRECTORIES
from verify import Entry

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('zstd'), 'zstd is required for archive tests')
class ArchiveTests(unittest.TestCase):
    def check_archive(self, entries):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.tar.zst'
            raw = io.BytesIO()
            with tarfile.open(fileobj=raw, mode='w') as archive:
                for entry in entries:
                    info = tarfile.TarInfo(entry.name)
                    info.uid, info.gid, info.mode = entry.uid, entry.gid, entry.mode
                    info.type = {'file': tarfile.REGTYPE, 'dir': tarfile.DIRTYPE,
                                 'symlink': tarfile.SYMTYPE, 'hardlink': tarfile.LNKTYPE}[entry.kind]
                    info.linkname = entry.link
                    info.size = len(entry.data) if entry.kind == 'file' else 0
                    archive.addfile(info, io.BytesIO(entry.data) if info.isfile() else None)
            path.write_bytes(subprocess.run(['zstd', '-q', '-c'], input=raw.getvalue(),
                                           stdout=subprocess.PIPE, check=True).stdout)
            return subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/verify.py'),
                                   '--archive', str(path)], capture_output=True, text=True)

    def test_final_headers_reject_writable_paths_and_nonroot_ownership(self):
        entries = clean()
        paths = [*DRIVER_DIRECTORIES, DRIVER,
                 'opt/democratic-csi/node_modules/@grpc/grpc-js/package.json',
                 'opt/csi-gatekeeper/csi-gatekeeper', 'usr/share/doc/csi-gatekeeper/LICENSE']
        for path in paths:
            original = next(e for e in entries if e.name == path)
            for change in ({'mode': original.mode | 0o020}, {'mode': original.mode | 0o002},
                           {'uid': 1000}, {'gid': 1000}):
                with self.subTest(path=path, change=change):
                    result = self.check_archive([e._replace(**change) if e.name == path else e
                                                 for e in entries])
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('application path', result.stderr.lower())
        for path in (*DRIVER_DIRECTORIES, DRIVER):
            with self.subTest(missing=path):
                self.assertNotEqual(self.check_archive([e for e in entries if e.name != path]).returncode, 0)

    def test_symlink_and_hardlink_header_policy(self):
        link = Entry('opt/democratic-csi/tool', 'symlink', 'package-lock.json', b'', mode=0o777)
        self.assertEqual(self.check_archive(clean() + [link]).returncode, 0)
        self.assertNotEqual(self.check_archive(clean() + [link._replace(uid=1000)]).returncode, 0)
        hardlink = link._replace(kind='hardlink', link='opt/democratic-csi/package-lock.json', mode=0o664)
        self.assertNotEqual(self.check_archive(clean() + [hardlink]).returncode, 0)

    def test_extraction_preserves_modes_under_umask_022(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'permissions.tar'
            with tarfile.open(source, 'w') as archive:
                for name, mode, kind in [('src', 0o775, tarfile.DIRTYPE),
                                         ('src/index.js', 0o664, tarfile.REGTYPE)]:
                    info = tarfile.TarInfo(name)
                    info.mode, info.type = mode, kind
                    archive.addfile(info)
            destination = root / 'extracted'
            destination.mkdir()
            subprocess.run(['tar', '--same-permissions', '--no-same-owner', '-xf', str(source),
                            '-C', str(destination)], umask=0o022, check=True)
            self.assertEqual((destination / 'src').stat().st_mode & 0o7777, 0o775)
            self.assertEqual((destination / 'src/index.js').stat().st_mode & 0o7777, 0o664)

    def test_compressed_contract_and_truncated_stream(self):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w') as archive:
            for name, kind, link, data, uid, gid, mode in clean():
                entry = tarfile.TarInfo(name)
                entry.uid, entry.gid, entry.mode = uid, gid, mode
                if kind == 'dir':
                    entry.type = tarfile.DIRTYPE
                    archive.addfile(entry)
                elif kind == 'symlink':
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
