"""Cross-compile the Windows launcher with llvm-mingw (host only)."""
import os
import shutil
import subprocess
import tempfile

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "launcher")


def _run(cmd, cwd, env):
    r = subprocess.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       universal_newlines=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError("%s failed:\n%s" % (os.path.basename(cmd[0]), r.stdout))


def make_launcher(toolchain_dir, out_exe, ico):
    bin_dir = os.path.join(toolchain_dir, "bin")
    env = dict(os.environ, PATH=bin_dir + os.pathsep + os.environ.get("PATH", ""))
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copy(os.path.join(HERE, "launcher.rc"), tmp)
        shutil.copy(os.path.join(HERE, "launcher.c"), tmp)
        shutil.copy(ico, os.path.join(tmp, "zhiraf.ico"))
        _run([os.path.join(bin_dir, "x86_64-w64-mingw32-windres"), "-c", "65001", "-O", "coff",
              "-i", "launcher.rc", "-o", "launcher_res.o"], tmp, env)
        # No C runtime: own entry point, so the only imports are kernel32 and user32.
        _run([os.path.join(bin_dir, "x86_64-w64-mingw32-clang"), "-municode", "-mwindows", "-Os", "-s",
              "-static", "-nostartfiles", "-nostdlib", "-fno-builtin", "-Wall", "-Werror",
              "-Wl,-e,launcher_entry", "-Wl,--no-insert-timestamp", "-o", "launcher.exe", "launcher.c", "launcher_res.o",
              "-lkernel32", "-luser32"], tmp, env)
        os.makedirs(os.path.dirname(os.path.abspath(out_exe)), exist_ok=True)
        shutil.copy(os.path.join(tmp, "launcher.exe"), out_exe)
