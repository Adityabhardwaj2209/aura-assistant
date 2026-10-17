"""Single fail-fast runner; optional read-only check of the running server."""
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--server', action='store_true', help='Also check the already-running local server')
    parser.add_argument('--model', action='store_true', help='Also load/download the embedding model')
    args = parser.parse_args()
    commands = [[sys.executable, '-m', 'unittest', 'test_router', 'test_followup', 'test_reliability','test_heart_brain','test_body','test_perception', '-v'],
                [sys.executable, 'test_all_aura.py']]
    if args.server:
        commands[-1].append('--server')
    if args.model:
        commands[-1].append('--model')
    logs = []
    for command in commands:
        env = dict(os.environ, PYTHONUTF8='1')
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace')
        output = result.stdout + result.stderr
        print(output)
        logs.append(output)
        if result.returncode:
            (ROOT/'aura_completion_report.txt').write_text('\n'.join(logs), encoding='utf-8')
            return result.returncode
    (ROOT/'aura_completion_report.txt').write_text('\n'.join(logs), encoding='utf-8')
    print('All selected checks passed. Live model, microphone, camera and avatar still need manual checks.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
