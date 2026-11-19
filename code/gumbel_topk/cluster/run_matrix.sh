#!/bin/bash
# Launch through the site's run wrapper, not directly on an access node.
set -euo pipefail
if [[ -z ${SLURM_JOB_ID:-} ]]; then
    echo 'This runner requires a SLURM allocation.' >&2
    exit 2
fi
# GCC is loaded by submit.sh and exported by sbatch. Reloading Lmod on the
# compute nodes currently fails because its Lua posix dependency is absent.
if [[ $(g++ -dumpfullversion) != 12.3.0 ]]; then
    echo 'Expected the gcc/12.3.0 environment inherited from submit.sh.' >&2
    exit 2
fi
TASK_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$TASK_ROOT"
export OMP_DYNAMIC=FALSE
export OMP_PROC_BIND=close
export OMP_PLACES=cores
GTOPK_PROFILE=${1:-smoke}
GTOPK_N=${2:-1000000}
GTOPK_K=${3:-all}
GTOPK_KS=(20 1000 10000)
GTOPK_SUFFIX=
if [[ $GTOPK_K != all ]]; then
    case "$GTOPK_K" in 20|1000|10000) ;; *) echo 'Unsupported K' >&2; exit 2 ;; esac
    GTOPK_KS=("$GTOPK_K")
    GTOPK_SUFFIX="-k${GTOPK_K}"
fi
GTOPK_RESULT="$TASK_ROOT/results/${GTOPK_PROFILE}-n${GTOPK_N}${GTOPK_SUFFIX}-job${SLURM_JOB_ID}"
mkdir -p "$TASK_ROOT/results"
# The report directory is created exclusively by benchmark.py.
{
    date -Is
    hostname
    uname -a
    printf 'Inherited modules: %s\n' "${LOADEDMODULES:-unset}"
    g++ --version
    python3 --version
    lscpu
    ldd build/gumbel_topk
    cat /proc/meminfo
    cat build/build-command.txt
    cat build/build.log
} > "${GTOPK_RESULT}-environment.txt" 2>&1
case "$GTOPK_PROFILE" in
    smoke)
        python3 benchmark.py --environment-label lomonosov2 --output "$GTOPK_RESULT" \
            --sizes "$GTOPK_N" --k 20 1000 --weight-pattern uniform skewed \
            --threads 1 2 4 8 14 --repeat 3 --warmup 1
        ;;
    full)
        python3 benchmark.py --environment-label lomonosov2 --output "$GTOPK_RESULT" \
            --sizes "$GTOPK_N" --k "${GTOPK_KS[@]}" --weight-pattern uniform skewed \
            --threads 1 2 4 8 14 --repeat 7 --warmup 1
        ;;
    *) echo "Unknown profile: $GTOPK_PROFILE" >&2; exit 2 ;;
esac
