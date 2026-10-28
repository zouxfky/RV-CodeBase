#!/usr/bin/env python3
"""Build the TACLeBench (Zicond extension) dataset from a TACLeBench checkout (bench/kernel, bench/sequential, bench/app).

    python3 -I benchmark/tacle/build.py --tacle <tacle-bench> [--repeat-json repeat.json]

Each program keeps its own files. The file with <name>_main (or the override
below) is the optimization target; main() is moved into a fixed harness that
calls <name>_init/_main/_return TACLE_REPEAT times and prints the summed result.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
from compact import squeeze, strip_comments  # noqa: E402

SUITE_DIR = Path(__file__).resolve().parent
GROUPS = ["kernel", "sequential", "app"]
SKIP = re.compile(r"(changelog|copyright|readme|license)", re.I)
# Programs whose hot code is not in the file that holds main().
# Programs larger than this (code + supporting files, after comment
# stripping) are left out: each row should stay small and fast to build.
MAX_LINES = 2800
TARGET = {"rijndael_enc": "aes.c", "rijndael_dec": "aes.c"}
MERGE = {"bitcount": ["bitcnt_1.c", "bitcnt_2.c", "bitcnt_3.c", "bitcnt_4.c"]}
# Programs whose global state (simulated heaps, input cursors) n_init() does
# not reset: each repetition runs in a fresh forked child.
FORK = {"anagram", "audiobeam", "g723_enc", "huff_dec"}
MAIN_RE = re.compile(r"\nint\s+main\s*\(\s*(?:void)?\s*\)\s*\{.*?\n\}\n", re.S)
PROTO_RE = re.compile(r"\nint\s+main\s*\(\s*(?:void)?\s*\)\s*;")

BIG_INIT_RE = re.compile(r"\n((?:static\s+)?(?:const\s+)?[\w ]+?\s+(\w+)\s*\[[^\]\n]*\])\s*=\s*\{")


def split_data(code: str, limit: int = 20000) -> tuple[str, str]:
    """Move top-level array initializers larger than `limit` bytes out of the target."""
    data = []
    for m in reversed(list(BIG_INIT_RE.finditer(code))):
        depth, j = 0, m.end() - 1
        for j in range(m.end() - 1, len(code)):
            depth += {"{": 1, "}": -1}.get(code[j], 0)
            if depth == 0:
                break
        end = code.index(";", j) + 1
        if end - m.start() < limit:
            continue
        decl = re.sub(r"^static\s+", "", m.group(1))
        body = code[m.end() - 1:end]
        data.insert(0, decl + " = " + body)
        # Keep the element count so sizeof() still works on the extern.
        if re.search(r"\[\s*\]$", decl) and "{" not in body[1:]:
            count = len([x for x in body.strip("{};\n ").split(",") if x.strip()])
            decl = re.sub(r"\[\s*\]$", f"[{count}]", decl)
        code = code[:m.start()] + "\nextern " + decl + ";" + code[end:]
    return code, "\n\n".join(data) + "\n" if data else ""


def replace_fn(code: str, sig: str, body: str) -> str:
    """Replace the body of the function whose header matches regex `sig`."""
    m = re.search(sig + r"(?=(?:/\*.*?\*/\s*)?\{)", code, re.S)
    assert m, sig
    i = code.index("{", m.end() - 1)
    depth = 0
    for j in range(i, len(code)):
        depth += {"{": 1, "}": -1}.get(code[j], 0)
        if depth == 0:
            break
    return code[:i] + body + code[j + 1:]


# Larger workloads with random data for the branch-heavy kernels: the upstream
# inputs are tiny and sorted or all-positive, so every branch is predicted.
# Each entry is a list of (header regex or None, replacement); None means a
# plain text substitution given as (old, new).
WORKLOADS = {
    "countnegative": [
        (("#define MAXSIZE 20", "#define MAXSIZE 256"), None),
        (r"\nint countnegative_randomInteger\( void \)\s*", """{
  countnegative_seed = countnegative_seed * 1103515245u + 12345u;
  return ( int )( ( ( unsigned )countnegative_seed >> 16 ) & 0x1fff ) - 4096;
}"""),
        (r"\nint countnegative_return\( void \)\s*", """{
  return countnegative_postotal + countnegative_poscnt + countnegative_negtotal + countnegative_negcnt;
}"""),
    ],
    "binarysearch": [
        (("struct binarysearch_DATA binarysearch_data[ 15 ];",
          "#define binarysearch_N 4096\nstruct binarysearch_DATA binarysearch_data[ binarysearch_N ];"), None),
        (r"\nvoid binarysearch_init\( void \)\s*", """{
  int i, key = 0;
  binarysearch_initSeed();
  for ( i = 0; i < binarysearch_N; ++i ) {
    key += 1 + ( binarysearch_randomInteger() & 3 );
    binarysearch_data[ i ].key = key;
    binarysearch_data[ i ].value = binarysearch_randomInteger();
  }
}"""),
        (r"\nlong binarysearch_randomInteger\( void \)\s*", """{
  binarysearch_seed = binarysearch_seed * 1103515245u + 12345u;
  return ( ( unsigned )binarysearch_seed >> 16 ) & 0x7fff;
}"""),
        (("up = 14;", "up = binarysearch_N - 1;"), None),
        (r"\nvoid _Pragma\( \"entrypoint\" \) binarysearch_main\( void \)\s*", """{
  int i, sum = 0;
  for ( i = 0; i < 4096; i++ )
    sum += binarysearch_binary_search( binarysearch_randomInteger() & 0x3fff );
  binarysearch_result = sum;
}"""),
    ],
    "bsort": [
        (("#define bsort_SIZE 100", "#define bsort_SIZE 1024"), None),
        (r"\nint bsort_Initialize\( int Array\[\] \)\s*", """{
  unsigned seed = 1;
  int Index;
  for ( Index = 0; Index < bsort_SIZE; Index ++ ) {
    seed = seed * 1103515245u + 12345u;
    Array[ Index ] = ( int )( seed >> 16 ) & 0x7fff;
  }
  return 0;
}"""),
        (r"\nint bsort_return\( void \)\s*", """{
  int Index, sum = 0;
  for ( Index = 0; Index < bsort_SIZE - 1; Index ++ )
    sum += ( bsort_Array[ Index ] <= bsort_Array[ Index + 1 ] ) * ( Index & 7 ) + bsort_Array[ Index ];
  return sum;
}"""),
    ],
    "bitonic": [
        (("int bitonic_a[ 32 ];", "#define bitonic_N 4096\nint bitonic_a[ bitonic_N ];"), None),
        (r"\nvoid bitonic_init\( void \)\s*", """{
  unsigned seed = 1;
  int i;
  for ( i = 0; i < bitonic_N; i++ ) {
    seed = seed * 1103515245u + 12345u;
    bitonic_a[ i ] = ( int )( seed >> 16 ) & 0x7fff;
  }
}"""),
        (r"\nint bitonic_return\( void \)\s*", """{
  int i, checksum = 0;
  for ( i = 0; i < bitonic_N; i++ )
    checksum += bitonic_a[ i ] * ( i & 15 );
  return checksum;
}"""),
        (("bitonic_sort( 0, 32, bitonic_ASCENDING );", "bitonic_sort( 0, bitonic_N, bitonic_ASCENDING );"), None),
    ],
}


def reshape(n: str, code: str) -> str:
    for a, b in WORKLOADS.get(n, []):
        if b is None:
            assert a[0] in code, (n, a[0])
            code = code.replace(a[0], a[1])
        else:
            code = replace_fn(code, a, b)
    return code


HARNESS = """#include <stdio.h>
void {n}_init(void);
void {n}_main(void);
int {n}_return(void);

int main(void)
{{
  long sum = 0;
  for (int r = 0; r < TACLE_REPEAT; r++) {{
    {n}_init();
    {n}_main();
    sum += {n}_return();
  }}
  printf("result %ld\\n", sum);
  return 0;
}}
"""

FORK_HARNESS = """#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/wait.h>
void {n}_init(void);
void {n}_main(void);
int {n}_return(void);

int main(void)
{{
  long sum = 0;
  for (int r = 0; r < TACLE_REPEAT; r++) {{
    int st;
    pid_t pid = fork();
    if (pid == 0) {{
      {n}_init();
      {n}_main();
      _exit({n}_return() & 0xff);
    }}
    if (pid < 0 || waitpid(pid, &st, 0) < 0 || !WIFEXITED(st))
      return 1;
    sum += WEXITSTATUS(st);
  }}
  printf("result %ld\\n", sum);
  return 0;
}}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tacle", required=True)
    ap.add_argument("--repeat-json", default=str(SUITE_DIR / "repeat.json"), help="{name: repeat} measured on the board")
    args = ap.parse_args()
    repeat = json.loads(Path(args.repeat_json).read_text()) if args.repeat_json else {}
    rows = []
    for group in GROUPS:
        for d in sorted((Path(args.tacle) / "bench" / group).iterdir()):
            n = d.name
            files = {str(p.relative_to(d)): p.read_text(encoding="latin-1").replace("\r\n", "\n").rstrip("\n") + "\n"
                     for p in sorted(d.rglob("*")) if p.is_file() and not SKIP.search(p.name)}
            files = {k: squeeze(strip_comments(v)) if k.endswith((".c", ".h")) else v for k, v in files.items()}
            if sum(v.count("\n") for v in files.values()) > MAX_LINES:
                print("skip (too large):", n)
                continue
            main_file = next((k for k, v in files.items() if k.endswith(".c") and MAIN_RE.search(v)), None)
            assert main_file, n
            files[main_file] = PROTO_RE.sub("\n", MAIN_RE.sub("\n", files[main_file]))
            target = TARGET.get(n, main_file)
            code = files.pop(target)
            for extra in MERGE.get(n, []):
                code += "\n/* ---- " + extra + " ---- */\n" + files.pop(extra)
            code, data = split_data(reshape(n, code))
            if data:
                files[f"{n}_data.c"] = data
            files["harness.c"] = (FORK_HARNESS if n in FORK else HARNESS).format(n=n)
            sources = ["harness.c"] + sorted(k for k in files if k.endswith(".c") and k != "harness.c"
                                             and not re.search(r"#include\s+\"" + re.escape(k) + "\"",
                                                               code + "".join(files.values())))
            rows.append({
                "id": f"tacle/{n}", "suite": "tacle", "group": group, "extension": "zicond",
                "target_file": target, "code": code, "files": files, "compile_sources": sources,
                "compile_defs": f"-w -DTACLE_REPEAT={int(repeat.get(n, 1))}",
                "output_filter": "", "preserve_functions": [], "required_functions": [f"{n}_main"]
                if target == main_file else [],
            })
    # Keep only the programs listed for this suite in classes.json.
    tasked = set().union(*json.loads((SUITE_DIR.parent / "classes.json").read_text())["tacle"].values())
    rows = [r for r in rows if r["id"] in tasked]
    out = SUITE_DIR / "dataset.jsonl"
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"wrote {len(rows)} rows to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
