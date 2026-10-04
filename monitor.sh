#!/bin/sh
# Send one command to the QEMU monitor of the test VM, e.g.:
#   ./monitor.sh "screendump /home/general/vm/win7/screen.png -f png"
printf '%s\n' "$1" | nc -U -q 2 /home/general/vm/win7/monitor.sock > /dev/null
