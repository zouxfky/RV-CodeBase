"""Per-extension settings for stage 3: target -march and the guidance prompt.

The -march strings match benchmark/common/extensions.py, so the dataset and the
benchmarks target the same instructions.
"""

from pathlib import Path


PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"

EXTENSIONS = {
    "RVV": {"march": "rv64gcv", "guidance": "3-ext-rvv.md"},
    "B": {"march": "rv64gc_zba_zbb_zbc_zbs", "guidance": "3-ext-b.md"},
    "Zicond": {"march": "rv64gc_zicond_zba_zbb", "guidance": "3-ext-zicond.md"},
    "IME": {"march": "rv64gcv", "guidance": "3-ext-ime.md"},
}


def check_extension(extension: str) -> str:
    value = str(extension).strip()
    if value not in EXTENSIONS:
        raise ValueError(f"unknown extension: {value!r}, expected one of {sorted(EXTENSIONS)}")
    return value


def march_for(extension: str) -> str:
    return EXTENSIONS[check_extension(extension)]["march"]


def guidance_for(extension: str) -> str:
    path = PROMPTS_DIR / EXTENSIONS[check_extension(extension)]["guidance"]
    return path.read_text(encoding="utf-8").strip()


def compile_cmd_for(template: str, extension: str) -> str:
    return template.replace("{march}", march_for(extension))
