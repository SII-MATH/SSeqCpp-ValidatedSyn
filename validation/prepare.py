#!/usr/bin/env python3
"""Copy only the configured original E2/map inputs into a new run directory."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess


def prepare(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or destination.exists():
        raise ValueError('A fresh, nonexistent run directory is required')
    config = json.loads((source / 'ss.json').read_text())
    files = {'ss.json'}
    for section in ('rings', 'modules', 'maps', 'maps_v2'):
        for row in config.get(section, []):
            if 'path' in row:
                files.add(row['path'])
    for name in files:
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError(f'Unsafe input path: {name}')
        if not (source / relative).is_file():
            raise FileNotFoundError(source / relative)
    # Initial tables must contain only pending d2 rows and the two units.
    # A computed SS state is not an acceptable starting input.
    initial_rows = units = 0
    for row in config['rings'] + config['modules']:
        database = source / row['path']
        with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
            table = row['name'] + '_AdamsE2_ss'
            quoted = '"' + table.replace('"', '""') + '"'
            for s, t, level, differential in db.execute(
                    f'SELECT s,t,level,diff FROM {quoted}'):
                if level == 9998 and differential is None:
                    initial_rows += 1
                elif row['name'] in ('S0', 'tmf') and (s, t, level, differential) == (0, 0, 9000, ''):
                    units += 1
                else:
                    raise ValueError(f'Computed SS state in {database.name}: {(s,t,level,differential)}')
    if (initial_rows, units) != (745444, 2):
        raise ValueError(f'Unexpected CW49 seed census: {(initial_rows, units)}')
    destination.mkdir(parents=True)
    digests = []
    for name in sorted(files):
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['cp', '--reflink=auto', '--', str(source / name), str(target)], check=True)
        digest = hashlib.sha256((source / name).read_bytes()).hexdigest()
        digests.append(f'{digest}  {name}')
    (destination / 'initial-inputs.sha256').write_text('\n'.join(digests) + '\n')
    if (destination / 'log.db').exists() or any(destination.glob('cofseq_*.db')):
        raise AssertionError('Historical log or cofiber state imported')
    print(f'Prepared {len(files)} original input files; {initial_rows} pending d2 rows, {units} units; no historical log/cofiber state.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    prepare(args.source, args.destination)
