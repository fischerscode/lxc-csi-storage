#!/usr/bin/env python3
"""Validate locked APK inputs and the exact final runtime package set."""
import argparse
from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[1]


def locked(path=REPO / 'packages.lock'):
    packages = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        fields = line.split()
        if len(fields) != 3:
            raise ValueError('Invalid package lock fields')
        digest, relative, role = fields
        match = re.fullmatch(r'(main|community)/([a-zA-Z0-9+_.-]+)-([0-9][a-zA-Z0-9+_.~]*-r[0-9]+)\.apk', relative)
        if (not re.fullmatch(r'[a-f0-9]{64}', digest) or not match or
                not re.fullmatch(r'[a-zA-Z0-9+_.-]+', match[2]) or
                role not in ('runtime', 'build') or match[2] in packages):
            raise ValueError('Invalid or duplicate package lock entry')
        packages[match[2]] = (match[3], digest, relative, role)
    if not packages:
        raise ValueError('Empty package lock')
    return packages


def installed(data):
    packages = {}
    for block in data.split('\n\n'):
        fields = dict(line.split(':', 1) for line in block.splitlines() if ':' in line)
        if 'P' in fields:
            if fields['P'] in packages or fields.get('A') not in ('x86_64', 'noarch'):
                raise ValueError('Duplicate package or unexpected architecture')
            packages[fields['P']] = fields['V']
    expected = {name: value[0] for name, value in locked().items() if value[3] == 'runtime'}
    if packages != expected:
        raise ValueError('Installed packages differ from locked runtime: '
                         + str(sorted(set(packages.items()) ^ set(expected.items()))))
    return packages


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--installed', type=Path)
    args = parser.parse_args()
    if args.installed:
        for name, version in sorted(installed(args.installed.read_text()).items()):
            print(name + '\t' + version)
    else:
        for _, digest, relative, role in sorted(locked().values(), key=lambda p: p[2]):
            print(digest, relative, role)
