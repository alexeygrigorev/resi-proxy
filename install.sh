#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
UV_THREADPOOL_SIZE=1 NODE_OPTIONS=--v8-pool-size=1 npm ci --ignore-scripts --no-audit --no-fund
python3 - <<'PY'
import os, pathlib, pwd, shutil, sys
source = pathlib.Path.cwd()
home = pathlib.Path(pwd.getpwuid(os.getuid()).pw_dir)
root = home / '.local/share/resi-proxy'
root.mkdir(parents=True, exist_ok=True)
for directory in ('bin', 'lib', 'node_modules', 'box'):
    shutil.copytree(source / directory, root / directory, dirs_exist_ok=True)
for filename in ('package.json', 'package-lock.json'):
    shutil.copy2(source / filename, root / filename)
units = home / '.config/systemd/user'
units.mkdir(parents=True, exist_ok=True)
for template in (source / 'systemd').iterdir():
    text = template.read_text().replace('@ROOT@', str(root)).replace('@NODE@', shutil.which('node')).replace('@PYTHON@', sys.executable)
    (units / template.name).write_text(text)
binpath = home / '.local/bin'
binpath.mkdir(parents=True, exist_ok=True)
link = binpath / 'proxy'
if link.exists() or link.is_symlink():
    if not link.is_symlink() or link.resolve() != root / 'bin/proxy':
        raise SystemExit('Existing proxy command differs; inspect it before replacing')
else:
    link.symlink_to(root / 'bin/proxy')
print(f'Installed {link}')
PY
systemctl --user daemon-reload
