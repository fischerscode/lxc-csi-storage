"""Minimal synthetic Alpine rootfs for finalizer/archive policy regression tests."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from finalize import finalize
from package_lock import locked


def prepare(root):
    config = json.loads((ROOT / 'build-config.json').read_text())
    files = {
        'etc/rc.conf': '#rc_sys=""\n',
        'etc/inittab': '::sysinit:/sbin/openrc sysinit\n::sysinit:/sbin/openrc boot\n'
                       '::wait:/sbin/openrc default\n::shutdown:/sbin/openrc shutdown\n',
        'etc/shadow': 'root:*::0:::::\n',
        'etc/alpine-release': config['alpine_version'] + '\n',
        'etc/init.d/sshd': 'generate_host_keys() { ssh-keygen -A; }\n',
        'etc/ssh/sshd_config': 'Include /etc/ssh/sshd_config.d/*.conf\n',
        'opt/csi-gatekeeper/csi-gatekeeper': 'PUBLIC TEST PLACEHOLDER',
        'usr/share/doc/csi-gatekeeper/LICENSE': 'PUBLIC TEST NOTICE',
        'usr/share/doc/csi-gatekeeper/THIRD_PARTY_NOTICES.txt': 'PUBLIC TEST NOTICE',
        'usr/share/doc/csi-gatekeeper/BUILD_INFO.json': '{}',
        'opt/democratic-csi/package-lock.json': '{}',
        'opt/democratic-csi/node_modules/@grpc/grpc-js/package.json': '{}',
        'sbin/init': 'PUBLIC TEST PLACEHOLDER', 'sbin/openrc': 'PUBLIC TEST PLACEHOLDER',
        'lib/apk/db/installed': '\n\n'.join('P:' + name + '\nV:' + value[0] + '\nA:x86_64'
                                 for name, value in locked().items() if value[3] == 'runtime'),
    }
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    (root / 'etc/init.d').mkdir(exist_ok=True)
    finalize(root, 'v0.0.0-test', config)
    (root / 'usr/share/csi-storage/build-info.json').write_text(json.dumps({
        'schema_version': 1, 'template_version': 'v0.0.0-test'}))
