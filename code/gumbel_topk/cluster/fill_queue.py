"""Submit remaining agreed cases, respecting the site's three-job limit.

Invoke on an access node, one invocation at a time; performs no numerical work.
State is saved on the remote filesystem after each successful sbatch so a lost
SSH response does not require blindly repeating submissions.
"""
import json
from pathlib import Path
import re
import subprocess


def main():
    root = Path(__file__).resolve().parents[1]
    state_path = root / 'submission-state.json'
    if state_path.exists():
        state = json.loads(state_path.read_text())
    else:
        state = {'cases': [{'n': n, 'k': k, 'job_id': None} for n, k in [
            (100000, 'all'), (1000000, 'all'), (10000000, 'all'),
            (100000000, '20'), (100000000, '1000'), (100000000, '10000')]]}
    # Count all jobs of this account, including unrelated ones.
    user = subprocess.check_output(['id', '-un'], universal_newlines=True).strip()
    queue = subprocess.check_output(['squeue', '-u', user, '-h', '-o', '%i'],
                                    universal_newlines=True)
    slots = max(0, 3 - len(queue.splitlines()))
    for case in state['cases']:
        if slots == 0:
            break
        if case['job_id'] is not None:
            continue
        command = ['bash', str(root / 'cluster/submit.sh'), 'full', str(case['n']), case['k']]
        process = subprocess.run(command, cwd=str(root), stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, universal_newlines=True)
        if process.returncode:
            raise RuntimeError(process.stdout + process.stderr)
        found = re.findall(r'Submitted batch job (\d+)', process.stdout)
        if len(found) != 1:
            raise RuntimeError('Inspect queue before retrying: ' + process.stdout)
        case['job_id'] = int(found[0])
        temporary = state_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(state, indent=2) + '\n')
        temporary.replace(state_path)
        slots -= 1
        print(json.dumps(case), flush=True)
    print('STATE ' + json.dumps(state), flush=True)


if __name__ == '__main__':
    main()
