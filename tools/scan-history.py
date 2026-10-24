#!/usr/bin/env python3
"""Fallback history scan for exact DataImpulse credentials; never prints values."""
import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--env-file', type=Path, required=True)
args = parser.parse_args()
values = {}
for line in args.env_file.read_text().splitlines():
    words = shlex.split(line, comments=True)
    if words and words[0] == 'export':
        words.pop(0)
    if words and '=' in words[0]:
        key, value = words[0].split('=', 1)
        values[key] = value
needles = [os.environ.get(key, values.get(key, '')).encode() for key in ('DATAIMPULSE_USER', 'DATAIMPULSE_PASSWORD')]
if not all(needles):
    sys.exit('FAIL: credentials unavailable; scan not performed')
objects = subprocess.check_output(['git', 'rev-list', '--objects', '--all'], text=True).splitlines()
ids = sorted({line.split()[0] for line in objects})
# Avoid per-object process creation and avoid ever writing raw object data.
matched = 0
with subprocess.Popen(['git', 'cat-file', '--batch'], stdin=subprocess.PIPE, stdout=subprocess.PIPE) as batch:
    for oid in ids:
        batch.stdin.write((oid + '\n').encode())
        batch.stdin.flush()
        header = batch.stdout.readline().split()
        size = int(header[2])
        content = batch.stdout.read(size)
        batch.stdout.read(1)
        matched += int(any(needle in content for needle in needles))
    batch.stdin.close()
    batch.wait()
print(f'{"FAIL" if matched else "PASS"}: {len(ids)} reachable history objects scanned; {matched} contain exact DataImpulse credential values')
sys.exit(int(bool(matched)))
