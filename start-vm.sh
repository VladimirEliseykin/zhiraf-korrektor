#!/bin/sh
# Windows 7 x64 test VM: 4 GB RAM, 2 cores, no network.
# Screen: VNC on 127.0.0.1:5905. Control: QEMU monitor at monitor.sock.
cd /home/general/vm/win7 || exit 1
exec qemu-system-x86_64 \
  -name win7-test \
  -machine pc,accel=kvm \
  -cpu host \
  -smp 2 \
  -m 4096 \
  -rtc base=localtime \
  -drive file=win7.qcow2,if=ide,index=0,media=disk,format=qcow2 \
  -drive file=ru_windows_7_professional_with_sp1_x64_dvd_u_677024.iso,if=ide,index=1,media=cdrom,id=cd0 \
  -drive file=results.img,if=ide,index=2,media=disk,format=raw \
  -drive file=fat:floppy:/home/general/vm/win7/floppy,if=floppy,format=raw,readonly=on \
  -boot once=d \
  -nic none \
  -vga std \
  -usb -device usb-tablet \
  -display none \
  -vnc 127.0.0.1:5 \
  -monitor unix:/home/general/vm/win7/monitor.sock,server,nowait
