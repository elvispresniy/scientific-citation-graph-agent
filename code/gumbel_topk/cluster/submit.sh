#!/bin/bash
# Run from a login node after copying the bundle into ~/_scratch.
set -euo pipefail
if ! type module >/dev/null 2>&1; then
    source /etc/profile.d/modules.sh
fi
module add slurm gcc/12.3.0
TASK_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$TASK_ROOT"
GTOPK_PROFILE=${1:-smoke}
GTOPK_N=${2:-1000000}
GTOPK_K=${3:-all}
case "$GTOPK_PROFILE" in smoke|full) ;; *) echo 'Use smoke or full' >&2; exit 2 ;; esac
case "$GTOPK_K" in all|20|1000|10000) ;; *) echo 'Unsupported K' >&2; exit 2 ;; esac
if [[ ! $GTOPK_N =~ ^[1-9][0-9]*$ ]]; then
    echo 'N must be a positive integer' >&2
    exit 2
fi
if [[ ! -x build/gumbel_topk ]]; then
    echo 'Build the executable first; see cluster/README.md.' >&2
    exit 2
fi
mkdir -p results
sbatch -p test -N 1 -n 1 --ntasks-per-node=1 --exclusive --time=00:14:00 --export=ALL \
    --job-name="gtopk-$GTOPK_PROFILE" \
    --output="$TASK_ROOT/results/slurm-%j.out" \
    --error="$TASK_ROOT/results/slurm-%j.err" \
    run "$TASK_ROOT/cluster/run_matrix.sh" "$GTOPK_PROFILE" "$GTOPK_N" "$GTOPK_K"
