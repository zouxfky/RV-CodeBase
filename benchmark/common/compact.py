"""Shrink vendored C sources into small, self-contained files.

strip_comments  remove /* */ and // comments (string literals kept)
unifdef         resolve #if blocks on the given macros (needs the `unifdef` tool)
prune           drop prototypes and static inline functions nobody references
squeeze         collapse runs of blank lines
"""
import re
import subprocess

_TOKEN = re.compile(r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'|/\*.*?\*/|//[^\n]*', re.S)


def strip_comments(text: str) -> str:
    def sub(m: re.Match) -> str:
        s = m.group(0)
        if s.startswith("/*"):
            return "\n" * s.count("\n") or " "
        if s.startswith("//"):
            return ""
        return s
    return _TOKEN.sub(sub, text)


def unifdef(text: str, defined: dict[str, str] | None = None, undefined: list[str] | None = None) -> str:
    args = ["unifdef", "-b", "-t"]
    for k, v in (defined or {}).items():
        args.append(f"-D{k}={v}" if v is not None else f"-D{k}")
    args += [f"-U{u}" for u in undefined or []]
    r = subprocess.run(args, input=text, capture_output=True, text=True)
    if r.returncode not in (0, 1):
        raise RuntimeError(r.stderr)
    return r.stdout


def squeeze(text: str) -> str:
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def _match_brace(text: str, i: int) -> int:
    depth = 0
    for j in range(i, len(text)):
        depth += {"{": 1, "}": -1}.get(text[j], 0)
        if depth == 0:
            return j
    return len(text) - 1


_PROTO = re.compile(r"^[A-Za-z_][\w \t\*]*?\b(\w+)\s*\([^;{}]*\)\s*(?:__attribute__\s*\(\(.*?\)\)\s*)?;[ \t]*\n", re.M | re.S)
_ATTR = r"__attribute__\s*\(\([^\n]*\)\)[ \t]*\n"
# A static function, with any attribute lines (possibly in their own #if) before it.
_INLINE = re.compile(r"^(?:#[ \t]*if[^\n]*\n" + _ATTR + r"#[ \t]*endif[^\n]*\n\s*|" + _ATTR + r")*"
                     r"(?:__STATIC_FORCEINLINE|__STATIC_INLINE|static\s+inline|static\s+__inline|static)\b[^;{}()]*?\b(\w+)\s*\([^;{}]*\)\s*\{", re.M)


def prune(text: str, users: str) -> str:
    """Remove prototypes and static functions in `text` not named in `users` or in the rest of `text`."""
    while True:
        changed = False
        for m in list(_PROTO.finditer(text))[::-1]:
            name = m.group(1)
            rest = text[:m.start()] + text[m.end():]
            if name in ("if", "while", "for", "return", "sizeof"):
                continue
            if not re.search(r"\b" + name + r"\b", rest + users):
                text = rest
                changed = True
        for m in list(_INLINE.finditer(text))[::-1]:
            name = m.group(1)
            end = _match_brace(text, m.end() - 1) + 1
            rest = text[:m.start()] + text[end:]
            if not re.search(r"\b" + name + r"\b", rest + users):
                text = rest
                changed = True
        if not changed:
            return text


def compact(text: str, undefined: list[str], defined: dict[str, str] | None = None) -> str:
    return squeeze(unifdef(strip_comments(text), defined, undefined))
