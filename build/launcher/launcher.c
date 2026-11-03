/* Zhiraf.Korrektor launcher: starts python\pythonw.exe -m zhiraf.ui next to itself.
 * Only kernel32 and user32 are imported: no C runtime, so it starts even
 * on a Windows 7 without the universal CRT. */
#ifndef LAUNCHER_TEST
#include <windows.h>
#else
#include <stdio.h>
#include <string.h>
#include <wchar.h>
#endif

/* Returns the part of the command line after the program name, as is.
 * Only wchar_t comparisons and pointer arithmetic (wchar_t is 2 bytes on
 * Windows, 4 under the host test build). */
static const wchar_t *args_after_program(const wchar_t *cmdline)
{
    const wchar_t *p = cmdline;
    while (*p == L' ' || *p == L'\t')
        p++;
    if (*p == L'"') {
        p++;
        while (*p && *p != L'"')
            p++;
        if (*p == L'"')
            p++;
    } else {
        while (*p && *p != L' ' && *p != L'\t')
            p++;
    }
    while (*p == L' ' || *p == L'\t')
        p++;
    return p;
}

#ifndef LAUNCHER_TEST

static size_t wlen(const wchar_t *s)
{
    size_t n = 0;
    while (s[n])
        n++;
    return n;
}

static wchar_t *wput(wchar_t *dst, const wchar_t *src)
{
    while (*src)
        *dst++ = *src++;
    return dst;
}

static int fail(void)
{
    MessageBoxW(NULL,
                L"Не найден python\\pythonw.exe рядом с программой. "
                L"Скопируйте папку «Жираф.Корректор» целиком.",
                L"Жираф.Корректор", MB_OK | MB_ICONERROR);
    return 1;
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, LPWSTR cmd, int show)
{
    static const wchar_t py[] = L"\\python\\pythonw.exe\" -m zhiraf.ui";
    HANDLE heap = GetProcessHeap();
    DWORD cap = 32768;
    wchar_t *dir = HeapAlloc(heap, 0, cap * sizeof(wchar_t));
    wchar_t *line, *q;
    const wchar_t *tail;
    size_t n, tlen;
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    BOOL ok;
    unsigned char *z;
    size_t i;
    (void)inst; (void)prev; (void)cmd; (void)show;

    if (!dir)
        return fail();
    n = GetModuleFileNameW(NULL, dir, cap);
    if (n == 0 || n >= cap)
        return fail();
    while (n > 0 && dir[n - 1] != L'\\')
        n--;
    if (n == 0)
        return fail();
    dir[n - 1] = 0; /* folder without the trailing backslash */
    n--;

    tail = args_after_program(GetCommandLineW());
    tlen = wlen(tail);
    line = HeapAlloc(heap, 0, (n + wlen(py) + tlen + 4) * sizeof(wchar_t));
    if (!line)
        return fail();
    q = line;
    *q++ = L'"';
    q = wput(q, dir);
    q = wput(q, py);
    if (tlen) {
        *q++ = L' ';
        q = wput(q, tail);
    }
    *q = 0;

    z = (unsigned char *)&si;
    for (i = 0; i < sizeof si; i++)
        z[i] = 0;
    z = (unsigned char *)&pi;
    for (i = 0; i < sizeof pi; i++)
        z[i] = 0;
    si.cb = sizeof si;

    /* lpApplicationName is NULL: the quoted module path in the command line is used */
    ok = CreateProcessW(NULL, line, NULL, NULL, FALSE, 0, NULL, dir, &si, &pi);
    if (!ok)
        return fail();
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}

/* Own entry point: skips the C runtime start-up (see make_launcher.py). */
void WINAPI launcher_entry(void)
{
    ExitProcess((UINT)wWinMain(GetModuleHandleW(NULL), NULL, NULL, SW_SHOWDEFAULT));
}

#else /* LAUNCHER_TEST: read lines from stdin (UTF-8), print the parsed tail per line */

static size_t decode(const char *s, wchar_t *out)
{
    size_t n = 0;
    while (*s) {
        unsigned char c = (unsigned char)*s;
        unsigned cp;
        int more;
        if (c < 0x80) { cp = c; more = 0; }
        else if (c < 0xE0) { cp = c & 0x1F; more = 1; }
        else if (c < 0xF0) { cp = c & 0x0F; more = 2; }
        else { cp = c & 0x07; more = 3; }
        s++;
        while (more-- > 0)
            cp = (cp << 6) | ((unsigned char)*s++ & 0x3F);
        out[n++] = (wchar_t)cp;
    }
    out[n] = 0;
    return n;
}

static void encode(const wchar_t *w)
{
    for (; *w; w++) {
        unsigned cp = (unsigned)*w;
        if (cp < 0x80) putchar((int)cp);
        else if (cp < 0x800) { putchar(0xC0 | (cp >> 6)); putchar(0x80 | (cp & 0x3F)); }
        else { putchar(0xE0 | (cp >> 12)); putchar(0x80 | ((cp >> 6) & 0x3F)); putchar(0x80 | (cp & 0x3F)); }
    }
    putchar('\n');
}

int main(void)
{
    char line[4096];
    static wchar_t wide[4096];
    while (fgets(line, sizeof line, stdin)) {
        size_t l = strlen(line);
        if (l && line[l - 1] == '\n')
            line[l - 1] = 0;
        decode(line, wide);
        encode(args_after_program(wide));
    }
    return 0;
}

#endif
