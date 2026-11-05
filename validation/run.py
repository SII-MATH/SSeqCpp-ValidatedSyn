#!/usr/bin/env python3
"""Fresh calculation; historical records are used only for prefix comparison."""
import argparse
from collections import deque
import json
import hashlib
import os
from pathlib import Path
import resource
import subprocess
import time
import re
import sqlite3
from compare_prefix import compare

ROOT = Path(__file__).resolve().parents[1]


def run(binary, directory, rounds, stem_max, *, official_log=None,
        completed=None, previous_status=None):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    binary, directory = Path(binary).resolve(), Path(directory).resolve()
    if official_log is None:
        raise ValueError('An official log is required for the read-only ordinary-prefix comparison')
    if stem_max != 261:
        raise ValueError('The fixed CW49 reference requires the full stem range 0..261')
    official_log = Path(official_log).resolve()
    if not official_log.is_file():
        raise FileNotFoundError(official_log)
    if completed is not None:
        raise ValueError('The staged rerun must start fresh; the earlier mixed-Syn run is ineligible')
    if completed is None and (directory / 'log.db').exists():
        raise ValueError('This command requires a fresh prepared seed, with no log.db')
    if not (directory / 'initial-inputs.sha256').is_file():
        raise ValueError('Use validation/prepare.py first')
    status_file = directory / 'status.json'
    status = dict(previous_status) if previous_status is not None else {
              'phase': 'initializing', 'started': time.time(), 'round': 0,
              'targets': 201, 'historical_log_imported': False,
              'forbidden_rules': ['SynCs', 'SynCsIn']}
    status['schedule'] = 'ordinary without Syn -> exact prefix comparison -> validated rules -> 201 targets'
    status.update({'runner_pid': os.getpid(),
              'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
              'targets_sha256': hashlib.sha256((ROOT/'validation/targets.json').read_bytes()).hexdigest(),
              'source_commit': subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()})

    def save(**values):
        status.update(values)
        temporary=status_file.with_suffix('.tmp')
        temporary.write_text(json.dumps(status, indent=2) + '\n')
        temporary.replace(status_file)

    def command(arguments, name):
        tail = deque(maxlen=80)
        proc = subprocess.Popen([str(binary), *arguments], cwd=ROOT,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors='replace')
        save(command=name, child_pid=proc.pid, terminal_lines=0,
             last_progress='', command_started=time.time())
        updated, lines = time.monotonic(), 0
        for line in proc.stdout:
            tail.append(line)
            lines += 1
            if time.monotonic() - updated > 10:
                save(command=name, terminal_lines=lines,
                     last_progress=re.sub(r'\x1b\[[0-9;]*m','',line[-500:]).strip())
                updated = time.monotonic()
            if line.startswith('VALIDATED_CACHE '):
                save(cache_statistics=json.loads(line.removeprefix('VALIDATED_CACHE ')))
        code = proc.wait()
        proc.stdout.close()
        save(terminal_lines=lines, command_finished=time.time(), child_pid=None)
        if code:
            (directory / (name + '.error.log')).write_text(''.join(tail))
            save(phase='failed', command=name, exit_code=code)
            raise RuntimeError(f'{name} failed: see {directory / (name + ".error.log")}')
        # SQLite is authoritative only after the native command has committed.
        with sqlite3.connect((directory/'log.db').as_uri()+'?mode=ro',uri=True) as db:
            save(saved_log_rows=db.execute('SELECT count(*) FROM log').fetchone()[0])

    save()
    if completed is None:
        command(['reset', str(directory), 'confirm=1'], 'initialize')
    # No synthetic, zero-expansion or pullback flag is used in the published
    # ordinary prefix (all retained trials there have depth one). The upstream
    # auto command stops when a complete SS/cofiber iteration adds no facts.
    save(phase='ordinary', new_rules_enabled=False)
    command(['deduce', 'auto', str(directory), 'stem_min=0', 'stem_max=261',
             'num=10'], 'ordinary')
    save(phase='comparing-prefix')
    comparison = compare(directory/'log.db', official_log)
    (directory/'ordinary-comparison.json').write_text(json.dumps(comparison, indent=2)+'\n')
    save(ordinary_comparison={'passed':comparison['passed'], 'matched':comparison['matched'],
                             'report':'ordinary-comparison.json'})
    if not comparison['passed']:
        save(phase='prefix-mismatch')
        raise RuntimeError('Ordinary prefix differs from official log; new rules remain disabled')
    save(phase='deducing', new_rules_enabled=True)
    for number in range(1, rounds + 1):
        save(round=number)
        # The first enabling point is strictly after a successful comparison.
        command(['deduce', 'synthetic', str(directory)], f'validated-{number:03d}')
        command(['deduce', 'auto', str(directory), 'stem_min=0', f'stem_max={stem_max}',
                 'num=1', 'flags=validated_syn'], f'round-{number:03d}')
        acceptance_file = directory / 'acceptance.json'
        acceptance_file.unlink(missing_ok=True)
        save(command=f'verify-{number:03d}')
        with (directory / f'check-{number:03d}.log').open('w') as log:
            result = subprocess.run([str(binary), 'verify', str(directory),
                                     str(ROOT / 'validation/targets.json')], cwd=ROOT,
                                    stdout=log, stderr=subprocess.STDOUT)
        verify_code=result.returncode
        if not acceptance_file.is_file():
            save(phase='failed', command='verify', exit_code=verify_code)
            raise RuntimeError('Verification did not produce a result')
        acceptance = json.loads(acceptance_file.read_text())
        save(passed=acceptance['passed'], missing=acceptance['missing'],
             forbidden_outputs=acceptance['forbidden_outputs'])
        if acceptance['forbidden_outputs']:
            save(phase='failed')
            raise RuntimeError('Forbidden synthetic output detected')
        if verify_code == 0 and acceptance['passed'] == 201:
            save(phase='passed', completed=time.time())
            return
    save(phase='incomplete', completed=time.time())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--binary', type=Path, default=ROOT / 'build/bin/ss')
    parser.add_argument('--rounds', type=int, default=10)
    parser.add_argument('--stem-max', type=int, default=261)
    parser.add_argument('--official-log', type=Path, required=True,
                        help='Read only by the comparison; never passed to the native engine')
    args = parser.parse_args()
    run(args.binary, args.directory, args.rounds, args.stem_max, official_log=args.official_log)
