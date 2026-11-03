#!/bin/sh
# Usage: make_iso.sh <dist> <job_dir> <iso>
set -eu
if [ "$#" -ne 3 ]; then
    echo "usage: make_iso.sh <dist> <job_dir> <iso>" >&2
    exit 2
fi
exec xorriso -as mkisofs -iso-level 3 -J -joliet-long -R -V ZHIRAF -o "$3" \
    -graft-points "dist=$1" "job=$2"
