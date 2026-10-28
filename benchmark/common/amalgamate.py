"""Join a multi-file C program into one self-contained file.

Quoted #includes that resolve inside the given include directories (or next
to the including file) are pasted in place, each header once; <system>
includes are kept. Sources are appended in the order given.
"""
import re
from pathlib import Path

INC_RE = re.compile(r'^[ \t]*#[ \t]*include[ \t]*"([^"]+)"[^\n]*$', re.M)
ANGLE_RE = re.compile(r'^[ \t]*#[ \t]*include[ \t]*(?:"([^"]+)"|<([^>]+)>)[^\n]*$', re.M)


def amalgamate(sources: list[tuple[str, str]], include_dirs: list[Path], virtual: dict[str, str] | None = None,
               angle: bool = False, transform=None) -> str:
    """sources: (name, text) pairs. virtual: header name -> text for headers not on disk.
    angle: also inline <...> includes that resolve in include_dirs.
    transform: applied to each file before its includes are expanded (e.g. to
    resolve #ifs, so a header is pasted where it is really first included)."""
    transform = transform or (lambda t: t)
    virtual = virtual or {}
    seen: set[str] = set()

    def resolve(name: str, here: Path | None) -> tuple[str, str] | None:
        if name in virtual:
            return "v:" + name, virtual[name]
        for d in ([here] if here else []) + include_dirs:
            p = (d / name).resolve()
            if p.is_file():
                return str(p), p.read_text(encoding="latin-1")
        return None

    def expand(text: str, here: Path | None) -> str:
        def sub(m: re.Match) -> str:
            name = m.group(1) or m.group(2)
            hit = resolve(name, here if m.group(1) else None)
            if hit is None:
                return m.group(0)
            key, body = hit
            if key in seen:
                return ""
            seen.add(key)
            nhere = None if key.startswith("v:") else Path(key).parent
            return f"/* ---- {name} ---- */\n" + expand(transform(body), nhere) + "\n"
        return (ANGLE_RE if angle else INC_RE).sub(sub, text)

    parts = []
    for name, text in sources:
        here = Path(name).parent if Path(name).is_absolute() else None
        parts.append(f"/* ==== {Path(name).name} ==== */\n" + expand(transform(text), here))
    return "\n".join(parts)
