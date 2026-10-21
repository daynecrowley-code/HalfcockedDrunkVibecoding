#!/usr/bin/env python3
"""tinybrowse - a minimal text-mode web browser built for a tiny RAM footprint.

No JavaScript, no images, no CSS, no cache, no tabs. Only the rendered text
lines and link table of the *current* page are kept in memory; the raw HTML is
streamed through a parser and discarded. Stdlib only.

Usage:  tinybrowse.py [url]          interactive (curses, or plain prompt if
                                     curses is unavailable, e.g. Windows ARM)
        tinybrowse.py --plain [url]  force the plain prompt mode
        tinybrowse.py --dump url     print rendered page and peak RSS, then exit
"""
import gzip
import sys
import textwrap
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin

MAX_BYTES = 1_000_000  # hard cap on download size per page
SKIP = {"script", "style", "head", "noscript", "svg", "template", "iframe"}
BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
         "ul", "ol", "table", "blockquote", "pre", "section", "article",
         "header", "footer", "nav", "form", "hr", "dt", "dd"}


class Renderer(HTMLParser):
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base, self.links, self.out = base, [], []
        self.buf, self.skip, self.href, self.pre = [], 0, None, 0

    def flush(self):
        text = "".join(self.buf)
        self.buf.clear()
        if self.pre:
            self.out.extend(text.split("\n"))
        elif text.strip():
            self.out.extend(textwrap.wrap(" ".join(text.split()), 78) or [""])
        else:
            return
        self.out.append("")

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self.skip += 1
        elif self.skip:
            return
        if tag in BLOCK:
            self.flush()
        if tag == "pre":
            self.pre += 1
        elif tag == "li":
            self.buf.append("* ")
        elif tag[0] == "h" and len(tag) == 2 and tag[1].isdigit():
            self.buf.append("#" * int(tag[1]) + " ")
        elif tag == "a":
            h = dict(attrs).get("href")
            if h and not h.startswith(("javascript:", "#", "mailto:")):
                self.href = urljoin(self.base, h)
                self.links.append(self.href)
                self.buf.append("[%d]" % len(self.links))
        elif tag == "img":
            alt = dict(attrs).get("alt")
            if alt:
                self.buf.append("[img: %s]" % alt)

    def handle_endtag(self, tag):
        if tag in SKIP:
            self.skip = max(0, self.skip - 1)
        elif self.skip:
            return
        if tag in BLOCK:
            self.flush()
        if tag == "pre":
            self.pre = max(0, self.pre - 1)
        elif tag == "a":
            self.href = None

    def handle_data(self, data):
        if not self.skip:
            self.buf.append(data)


def fetch(url):
    """Return (final_url, lines, links). Raw HTML never outlives this call."""
    if "://" not in url:
        url = "https://" + url
    req = urllib.request.Request(url, headers={
        "User-Agent": "tinybrowse/0.1", "Accept-Encoding": "gzip",
        "Accept": "text/html,text/plain;q=0.9,*/*;q=0.1"})
    with urllib.request.urlopen(req, timeout=15) as r:
        final = r.geturl()
        raw = r.read(MAX_BYTES)
        ctype = r.headers.get_content_type()
        charset = r.headers.get_content_charset() or "utf-8"
        gz = r.headers.get("Content-Encoding") == "gzip"
    if gz:
        try:
            raw = gzip.GzipFile(fileobj=__import__("io").BytesIO(raw)).read(MAX_BYTES * 4)
        except (EOFError, OSError):  # truncated by the size cap: keep what we got
            import zlib
            raw = zlib.decompressobj(31).decompress(raw)
    text = raw.decode(charset, "replace")
    del raw
    if ctype != "text/html":
        return final, text.splitlines(), []
    p = Renderer(final)
    p.feed(text)
    del text
    p.close()
    p.flush()
    return final, p.out, p.links


def peak_mb():
    try:
        import resource  # Unix
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    except ImportError:  # Windows: PeakWorkingSetSize via ctypes
        try:
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                    (n, ctypes.c_size_t) for n in (
                        "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                        "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                        "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
            pmc = PMC()
            pmc.cb = ctypes.sizeof(pmc)
            k32 = ctypes.windll.kernel32
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            ok = ctypes.windll.psapi.GetProcessMemoryInfo(
                k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
            return pmc.PeakWorkingSetSize / 1048576 if ok else 0.0
        except Exception:
            return 0.0


def ui(scr, start):
    import curses
    curses.curs_set(0)
    hist, url, lines, links, top = [], "", [], [], 0
    status = "o:open  j/k:scroll  space/b:page  1-9..Enter:follow link  B:back  /:find  q:quit"

    def ask(prompt):
        h, w = scr.getmaxyx()
        scr.addnstr(h - 1, 0, " " * (w - 1), w - 1)
        scr.addnstr(h - 1, 0, prompt, w - 1)
        curses.curs_set(1)
        curses.echo()
        s = scr.getstr(h - 1, len(prompt), 300).decode("utf-8", "replace").strip()
        curses.noecho()
        curses.curs_set(0)
        return s

    def go(target, push=True):
        nonlocal url, lines, links, top, status
        status = "loading " + target
        draw()
        try:
            u, l, k = fetch(target)
        except Exception as e:
            status = "error: %s" % e
            return
        if push and url:
            hist.append(url)
        url, lines, links, top = u, l, k, 0
        status = "ok"

    def draw():
        h, w = scr.getmaxyx()
        scr.erase()
        scr.addnstr(0, 0, url or "(no page)", w - 1, curses.A_REVERSE)
        for i, ln in enumerate(lines[top:top + h - 2]):
            scr.addnstr(i + 1, 0, ln, w - 1)
        scr.addnstr(h - 1, 0, "%s | %.0fMB peak | %d%%" % (
            status, peak_mb(), 100 * min(len(lines), top + h - 2) // max(1, len(lines))), w - 1)
        scr.refresh()

    if start:
        go(start)
    num = ""
    while True:
        draw()
        h = scr.getmaxyx()[0]
        c = scr.getch()
        page = h - 2
        if c == ord("q"):
            return
        elif c in (ord("j"), curses.KEY_DOWN):
            top = min(max(0, len(lines) - 1), top + 1)
        elif c in (ord("k"), curses.KEY_UP):
            top = max(0, top - 1)
        elif c in (ord(" "), curses.KEY_NPAGE):
            top = min(max(0, len(lines) - 1), top + page)
        elif c in (ord("b"), curses.KEY_PPAGE):
            top = max(0, top - page)
        elif c == ord("g"):
            top = 0
        elif c == ord("G"):
            top = max(0, len(lines) - page)
        elif c == ord("o"):
            t = ask("open: ")
            if t:
                go(t)
        elif c == ord("B") and hist:
            go(hist.pop(), push=False)
        elif c == ord("/"):
            q = ask("find: ").lower()
            for i in list(range(top + 1, len(lines))) + list(range(0, top)):
                if q and q in lines[i].lower():
                    top = i
                    break
        elif ord("0") <= c <= ord("9"):
            num += chr(c)
            status = "link #" + num + " (Enter to follow)"
        elif c in (10, 13) and num:
            n, num = int(num), ""
            if 1 <= n <= len(links):
                go(links[n - 1])
            else:
                status = "no such link"
        else:
            num = ""


def plain(start):
    """Curses-free mode: prints the page, then reads a command per line."""
    url, lines, links, top = "", [], [], 0
    rows = 24
    cmd = start
    while True:
        if cmd and cmd.startswith(("http", "www")) or (cmd and "." in cmd and " " not in cmd and not cmd.isdigit()):
            try:
                url, lines, links = fetch(cmd)
                top = 0
            except Exception as e:
                print("error:", e)
        elif cmd and cmd.isdigit() and 1 <= int(cmd) <= len(links):
            try:
                url, lines, links = fetch(links[int(cmd) - 1])
                top = 0
            except Exception as e:
                print("error:", e)
        elif cmd in ("", "n") and lines:
            top = min(top + rows, max(0, len(lines) - 1))
        elif cmd == "p":
            top = max(0, top - rows)
        elif cmd == "q":
            return
        elif cmd:
            print("unknown command")
        if lines:
            print("\n".join(lines[top:top + rows]))
            print("-- %s | %.0fMB peak | line %d/%d" % (url, peak_mb(), top, len(lines)))
        print("[Enter/n]=next  p=prev  <number>=follow link  <url>=open  q=quit")
        try:
            cmd = input("> ").strip()
        except EOFError:
            return


def main():
    a = sys.argv[1:]
    if a[:1] == ["--dump"] and len(a) > 1:
        u, lines, links = fetch(a[1])
        print("\n".join(lines))
        print("\n--- %d links, peak RSS %.1f MB ---" % (len(links), peak_mb()), file=sys.stderr)
        return
    force = a[:1] == ["--plain"]
    if force:
        a = a[1:]
    try:
        if force:
            raise ImportError
        import curses
    except ImportError:
        return plain(a[0] if a else None)
    curses.wrapper(ui, a[0] if a else None)


if __name__ == "__main__":
    main()
