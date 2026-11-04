#!/usr/bin/env python3
"""Start a fresh calculation; historical proof records are never read."""
import argparse
from collections import deque
import json
import hashlib
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def run(binary, directory, rounds, stem_max):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    binary, directory = Path(binary).resolve(), Path(directory).resolve()
    if (directory / 'log.db').exists():
        raise ValueError('This command requires a fresh prepared seed, with no log.db')
    if not (directory / 'initial-inputs.sha256').is_file():
        raise ValueError('Use validation/prepare.py first')
    status_file = directory / 'status.json'
    status = {'phase': 'initializing', 'started': time.time(), 'round': 0,
              'targets': 201, 'historical_log_imported': False,
              'forbidden_rules': ['SynCs', 'SynCsIn'], 'runner_pid': os.getpid(),
              'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
              'targets_sha256': hashlib.sha256((ROOT/'validation/targets.json').read_bytes()).hexdigest(),
              'source_commit': subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()}

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
        save(command=name, child_pid=proc.pid)
        updated, lines = time.monotonic(), 0
        for line in proc.stdout:
            tail.append(line)
            lines += 1
            if time.monotonic() - updated > 10:
                save(command=name, progress_lines=lines, last_progress=line[-500:].strip())
                updated = time.monotonic()
        code = proc.wait()
        if code:
            (directory / (name + '.error.log')).write_text(''.join(tail))
            save(phase='failed', command=name, exit_code=code)
            raise RuntimeError(f'{name} failed: see {directory / (name + ".error.log")}')

    save()
    command(['reset', str(directory), 'confirm=1'], 'initialize')
    save(phase='deducing')
    for number in range(1, rounds + 1):
        save(round=number)
        # Ordinary deduction and the validated producers share the fresh state.
        command(['deduce', 'auto', str(directory), 'stem_min=0', f'stem_max={stem_max}',
                 'num=1', 'flags=validated_syn,zero,pullback'], f'round-{number:03d}')
        command(['deduce', 'synthetic', str(directory)], f'validated-{number:03d}')
        acceptance_file = directory / 'acceptance.json'
        acceptance_file.unlink(missing_ok=True)
        with (directory / f'check-{number:03d}.log').open('w') as log:
            result = subprocess.run([str(binary), 'verify', str(directory),
                                     str(ROOT / 'validation/targets.json')], cwd=ROOT,
                                    stdout=log, stderr=subprocess.STDOUT)
        if not acceptance_file.is_file():
            save(phase='failed', command='verify', exit_code=result.returncode)
            raise RuntimeError('Verification did not produce a result')
        acceptance = json.loads(acceptance_file.read_text())
        save(passed=acceptance['passed'], missing=acceptance['missing'],
             forbidden_outputs=acceptance['forbidden_outputs'])
        if acceptance['forbidden_outputs']:
            save(phase='failed')
            raise RuntimeError('Forbidden synthetic output detected')
        if result.returncode == 0 and acceptance['passed'] == 201:
            save(phase='passed', completed=time.time())
            return
    save(phase='incomplete', completed=time.time())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--binary', type=Path, default=ROOT / 'build/bin/ss')
    parser.add_argument('--rounds', type=int, default=10)
    parser.add_argument('--stem-max', type=int, default=261)
    args = parser.parse_args()
    run(args.binary, args.directory, args.rounds, args.stem_max)
