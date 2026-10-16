#!/usr/bin/env python3
"""Record public build inputs without runner paths, environment or credentials."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]


def command(*args):
    return subprocess.check_output(args, cwd=REPO, text=True).strip()


def build_info(version):
    inputs = [REPO / 'build-config.json', *sorted((REPO / 'scripts').glob('*.sh')),
              *sorted((REPO / 'scripts').glob('*.py'))]
    inputs += [p for p in (REPO / 'packages.lock', REPO / 'keys/alpine-release.asc') if p.exists()]
    return {
        'schema_version': 1,
        'template_version': version,
        'source_commit': command('git', 'rev-parse', 'HEAD'),
        'source_date_epoch': int(command('git', 'log', '-1', '--format=%ct')),
        'working_tree_clean': not bool(command('git', 'status', '--porcelain',
                                               '--untracked-files=normal')),
        'inputs_sha256': {p.relative_to(REPO).as_posix():
                         hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
        'pins': json.loads((REPO / 'build-config.json').read_text()),
        'builder_tools': {tool: command(tool, '--version').splitlines()[0]
                          for tool in ('gpgv', 'tar', 'zstd')},
    }


if __name__ == '__main__':
    print(json.dumps(build_info(sys.argv[1]), indent=2) + '\n', end='')
