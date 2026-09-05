"""Capture Python and native stacks before terminating a stalled datatest run."""

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path


def main() -> int:
    """Bound the test process, stack capture, and process-group cleanup."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True)
    parser.add_argument('--seconds', type=int, default=60)
    parser.add_argument('--sudo-gdb', action='store_true')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9-]+', args.label) or not 1 <= args.seconds <= 180:
        parser.error('Use a simple label and a timeout from 1 to 180 seconds.')
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('Provide the test executable after --.')

    root = Path(__file__).resolve().parents[2]
    output = root / 'playground' / args.label
    output.mkdir(parents=True)
    child_env = dict(os.environ)
    child_env.update(
        PYTHONHOME=sys.base_prefix,
        PYTHONPATH=str(Path(__file__).parent / 'diagnostic_python'),
        PYTHONDONTWRITEBYTECODE='1',
        LD_LIBRARY_PATH=f'{sys.base_prefix}/lib:{os.environ.get("LD_LIBRARY_PATH", "")}',
        LLVM_PROFILE_FILE=str(output / 'coverage-%p.profraw'),
        MONTY_DIAG_DUMP_AFTER=str(max(1, args.seconds // 2)),
    )
    started = time.monotonic()
    timed_out = False
    native_result = None
    with (output / 'test.log').open('x') as log:
        process = subprocess.Popen(
            command, cwd=root, env=child_env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
        )
        print(f'pid={process.pid} label={args.label} deadline={args.seconds}s', flush=True)
        try:
            process.wait(timeout=args.seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            debugger_env = dict(os.environ)
            debugger_env.pop('PYTHONHOME', None)
            debugger_env.pop('PYTHONPATH', None)
            debugger = ['sudo', '-n', 'gdb'] if args.sudo_gdb else ['gdb']
            with (output / 'native-stacks.log').open('x') as stacks:
                try:
                    result = subprocess.run(
                        [
                            *debugger,
                            '-nx',
                            '-batch',
                            '-ex',
                            'set pagination off',
                            '-ex',
                            'set debuginfod enabled off',
                            '-ex',
                            'thread apply all bt 24',
                            '-p',
                            str(process.pid),
                        ],
                        cwd=root,
                        env=debugger_env,
                        stdout=stacks,
                        stderr=subprocess.STDOUT,
                        timeout=25,
                        check=False,
                    )
                    native_result = result.returncode
                except (OSError, subprocess.TimeoutExpired) as exc:
                    native_result = str(exc)
        finally:
            if process.poll() is None:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    with suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait()

    receipt = {
        'label': args.label,
        'command': command,
        'timeout': timed_out,
        'exit_code': process.returncode,
        'elapsed_seconds': round(time.monotonic() - started, 3),
        'native_debugger_result': native_result,
    }
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt), flush=True)
    return 124 if timed_out else process.returncode


if __name__ == '__main__':
    sys.exit(main())
