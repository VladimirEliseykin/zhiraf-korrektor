# End-to-end check of the Windows folder in the Windows 7 VM

Host only; none of this goes into the shipped folder. The VM (`~/vm/win7/start-vm.sh`, 4 GB, no network) is already
running; do not start or stop it.

1. Build the folder: `python -m build.build_dist` (result `~/vm/win7/dist/Жираф.Корректор`).
2. Make the job (sample documents come from docfactory and stay outside git):
   `python3 -m build.vm.make_job <job_dir> <samples_dir>`  
   `<samples_dir>` holds `Образец.docx`, `Образец.doc`, `sample.docx`. Every call writes a new `id.txt`; `C:\watcher.cmd`
   in the VM starts `<cd>:\job\run.cmd` whenever that id changes.
3. Make the ISO (volume `ZHIRAF`, folder at `\dist`, job at `\job`; about 7.7 GB, needs that much free disk):
   `sh build/make_iso.sh "$HOME/vm/win7/dist/Жираф.Корректор" <job_dir> ~/vm/win7/dist.iso`
4. Insert it: `printf 'change cd0 /home/general/vm/win7/dist.iso\n' | timeout 10 ncat -U ~/vm/win7/monitor.sock`
5. Wait (copying the folder takes minutes, the whole run about 15 to 25 minutes). Screenshots while waiting:
   `printf 'screendump /path/shot.png -f png\n' | timeout 10 ncat -U ~/vm/win7/monitor.sock`. The driver writes
   `shot-now` to `driver7.txt` 150 s after it starts the real exe; take the screenshot 30 s later, while the window runs.
6. Read the results from the FAT disk (the logs are cp866 or UTF-8 as noted):
   `mcopy -o -i "$HOME/vm/win7/results.img@@1048576" ::driver7.txt .` (UTF-8, the driver),
   `::gui7.txt` (UTF-8, the window check), `::log7.txt` (cp866, cmd), `::win-*.png`.

What `run.cmd` does: runs `win_check.py driver` with the `python.exe` of the CD. The driver copies the folder to
`<desktop>\Жираф Корректор тест` (Cyrillic and a space, no administrator rights), the samples to a second desktop
folder, removes the settings and the log (a first start), starts `win_check.py check` under the copy's `pythonw.exe`,
then the real `Жираф.Корректор.exe "…\Образец 2.docx"`, kills it after 180 s and reads the error log size.

Expected: `check exit=0` in `driver7.txt`; in `gui7.txt` the lock, `check finished … done`, the help mark visible, the
corrected copy saved and the original unchanged, a PDF with Arial, `.doc` opened, `link created True`,
`forbidden … loaded … []`, `error log (none)`. The clipboard text length after the window process ended is not 0.
Document texts never reach the logs (counts and states only).
