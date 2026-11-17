"""Small terminal UI toolkit for the creole-zoho CLI. Standard library only; degrades to plain text off a TTY.

Look: a clack-style left rail. An active prompt is drawn as
    ◆ Title                      (hint line)
    │ ❯ ◉ choice
    └
and collapses to a single `✔ Title  answer` line once answered. Esc steps back; Ctrl-C cancels.
"""
from __future__ import annotations

import getpass
import itertools
import os
import select
import shutil
import sys
import threading
import time
from typing import Optional

try:
    import termios
    import tty
except ImportError:  # Windows: no raw terminal → treated as non-interactive
    termios = tty = None  # type: ignore

BACK = object()  # sentinel returned by prompts when the user presses Esc


class Style:
    def __init__(self) -> None:
        self.on = sys.stdout.isatty() and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"

    def _c(self, code: str, s: str) -> str:
        return f"\033[{code}m{s}\033[0m" if self.on else s

    def bold(self, s): return self._c("1", s)
    def dim(self, s): return self._c("2", s)
    def accent(self, s): return self._c("38;5;80", s)
    def ok(self, s): return self._c("32", s)
    def warn(self, s): return self._c("33", s)
    def err(self, s): return self._c("31", s)
    def violet(self, s): return self._c("38;5;141", s)


S = Style()


def interactive() -> bool:
    return bool(termios) and sys.stdin.isatty() and sys.stdout.isatty()


def cols() -> int:
    return max(40, min(shutil.get_terminal_size((80, 24)).columns, 100))


def clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[: max(0, n - 1)].rstrip() + "…"


def ansi_len(s: str) -> int:
    import re
    return len(re.sub(r"\033\[[0-9;?]*[A-Za-z]", "", s))


# ───────────────────────────── static output ─────────────────────────────
LOGO = ["█▀▀ █▀█ █▀▀ █▀█ █   █▀▀", "█▄▄ █▀▄ ██▄ █▄█ █▄▄ ██▄"]


def banner(version: str) -> None:
    print()
    for i, line in enumerate(LOGO):
        tail = f"  {S.bold('zoho')} {S.dim('v' + version)}" if i == 0 else f"  {S.dim('Zoho Projects skills for AI agents')}"
        print(f"  {S.accent(line)}{tail}")
    print()


def box(lines: list, title: str = "", color=None) -> None:
    color = color or S.accent
    width = min(cols() - 4, max([ansi_len(l) for l in lines] + [ansi_len(title) + 4, 40]) + 2)
    top = f"╭─ {title} " if title else "╭"
    print(color(top + "─" * (width + 2 - ansi_len(top) + 1) + "╮"))
    for l in lines:
        print(color("│") + " " + l + " " * (width - ansi_len(l)) + " " + color("│"))
    print(color("╰" + "─" * (width + 2) + "╯"))


def done_line(title: str, answer: str) -> None:
    print(f"{S.ok('✔')} {S.bold(title)}  {S.dim(clip(answer, cols() - ansi_len(title) - 8))}")


def info(msg: str) -> None:
    print(f"{S.dim('│')}  {msg}")


# ───────────────────────────── keys ─────────────────────────────
def _key(fd: int) -> str:
    b = os.read(fd, 1)
    if b == b"\x1b":
        if select.select([fd], [], [], 0.05)[0]:
            rest = os.read(fd, 8)
            return {b"[A": "up", b"[B": "down", b"OA": "up", b"OB": "down", b"[H": "home", b"[F": "end"}.get(rest, "other")
        return "esc"
    if b in (b"\r", b"\n"):
        return "enter"
    if b == b" ":
        return "space"
    if b == b"\x03":
        return "ctrl-c"
    if b in (b"\x7f", b"\x08"):
        return "backspace"
    try:
        ch = b.decode()
    except UnicodeDecodeError:
        return "other"
    return ch if ch.isprintable() else "other"


class _Raw:
    def __enter__(self):
        self.fd = sys.stdin.fileno()
        self.old = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        sys.stdout.write("\033[?25l")
        sys.stdout.flush()
        return self.fd

    def __exit__(self, *exc):
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()


def _erase(n: int) -> None:
    if n:
        sys.stdout.write(f"\033[{n}F\033[J")


# ───────────────────────────── prompts ─────────────────────────────
def choose(title: str, items: list, *, multi: bool, selected=(), locked=(), default_index: int = 0,
           summary=None, can_back: bool = True, step: str = ""):
    """items: [(key, label, hint)]. Returns list of keys (multi) / one key (single) / BACK.

    Type to filter, ↑/↓ move, space toggle (multi), a = all (multi), enter confirm, esc back.
    """
    sel = set(selected) | set(locked)
    cur, query, drawn = default_index, "", 0
    width = cols()
    help_ = ("↑↓ move · space toggle · a all · type to filter · enter ok" if multi
             else "↑↓ move · type to filter · enter select") + (" · esc back" if can_back else "")
    with _Raw() as fd:
        try:
            while True:
                vis = [i for i in items if query.lower() in (i[1] + " " + i[0]).lower()] or items
                cur = min(cur, len(vis) - 1)
                tag = S.dim(step + " ") if step else ""
                out = [f"{S.accent('◆')} {tag}{S.bold(title)}  {S.dim(help_)}"]
                if query:
                    out.append(f"{S.dim('│')}  {S.dim('filter:')} {query}")
                for idx, (key, label, hint) in enumerate(vis):
                    focus = idx == cur
                    pointer = S.accent("❯") if focus else " "
                    if multi:
                        mark = S.ok("◉") if key in sel else S.dim("○")
                    else:
                        mark = S.ok("●") if focus else S.dim("○")
                    tag = S.dim("  required") if key in locked else ""
                    out.append(f"{S.dim('│')}  {pointer} {mark} {S.bold(label) if focus else label}{tag}")
                    if focus and hint:
                        out.append(f"{S.dim('│')}      {S.dim(clip(hint, width - 10))}")
                out.append(S.dim("└"))
                _erase(drawn)
                sys.stdout.write("\n".join(out) + "\n")
                sys.stdout.flush()
                drawn = len(out)
                k = _key(fd)
                if k == "ctrl-c":
                    raise KeyboardInterrupt
                if k == "esc":
                    if query:
                        query = ""
                    elif can_back:
                        _erase(drawn)
                        return BACK
                elif k == "up":
                    cur = (cur - 1) % len(vis)
                elif k == "down":
                    cur = (cur + 1) % len(vis)
                elif k == "space" and multi:
                    sel ^= {vis[cur][0]} - set(locked)
                elif k == "backspace":
                    query = query[:-1]
                elif k == "enter":
                    if multi and not sel:
                        continue
                    result = [i[0] for i in items if i[0] in sel] if multi else vis[cur][0]
                    _erase(drawn)
                    if summary:
                        done_line(title, summary(result))
                    return result
                elif multi and k == "a" and not query:
                    allk = {i[0] for i in items}
                    sel = allk if sel != allk else set(locked)
                elif len(k) == 1 and k.isprintable():
                    query += k
                    cur = 0
        except BaseException:
            _erase(drawn)
            raise


def text(title: str, *, default: str = "", hint: str = "", secret: bool = False, summary=None, step: str = ""):
    """Free-text prompt. Returns the string, or BACK when the user types '<'. Secret input is not echoed."""
    tag = S.dim(step + " ") if step else ""
    print(f"{S.accent('◆')} {tag}{S.bold(title)}" + (f"  {S.dim(hint)}" if hint else ""))
    suffix = f" {S.dim('[' + default + ']')}" if default else ""
    prompt = f"{S.dim('│')}  ❯{suffix} "
    try:
        raw = (getpass.getpass(prompt) if secret else input(prompt)).strip()
    except EOFError:
        raw = ""
    if raw == "<":
        return BACK
    val = raw or default
    if summary and S.on:
        _erase(2)
        done_line(title, summary(val))
    return val


def confirm(title: str, default: bool = True) -> bool:
    ans = input(f"{S.accent('◆')} {S.bold(title)} {S.dim('(Y/n)' if default else '(y/N)')} ").strip().lower()
    return default if not ans else ans.startswith("y")


class Spinner:
    """with Spinner('Installing…') as sp: ...; sp.ok('done') / sp.fail('why')  — static line when not a TTY."""

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, label: str) -> None:
        self.label, self._stop, self._t = label, threading.Event(), None

    def __enter__(self):
        self.t0 = time.time()
        if S.on and sys.stdout.isatty():
            self._t = threading.Thread(target=self._spin, daemon=True)
            self._t.start()
        return self

    def _spin(self) -> None:
        for f in itertools.cycle(self.FRAMES):
            if self._stop.is_set():
                return
            sys.stdout.write(f"\r{S.accent(f)} {self.label}")
            sys.stdout.flush()
            time.sleep(0.08)

    def _finish(self, mark: str, msg: str) -> None:
        self._stop.set()
        if self._t:
            self._t.join()
        sys.stdout.write("\r\033[K" if S.on and sys.stdout.isatty() else "")
        print(f"{mark} {msg}")

    def ok(self, msg: Optional[str] = None) -> None:
        self._finish(S.ok("✔"), msg or self.label)

    def warn(self, msg: str) -> None:
        self._finish(S.warn("!"), msg)

    def fail(self, msg: str) -> None:
        self._finish(S.err("✖"), msg)

    def __exit__(self, *exc):
        if not self._stop.is_set():
            self._finish(S.err("✖"), self.label)
        return False
