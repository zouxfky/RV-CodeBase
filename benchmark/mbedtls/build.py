"""Build the Mbed TLS (B extension) dataset from the vendored library in src/.

One row per algorithm timed by Mbed TLS 3.6.2 programs/test/benchmark.c.
Each row is built with a minimal configuration (CONFIG below: only the modules
that algorithm needs), and every #if on configuration or foreign-architecture
macros is resolved with unifdef, so a row is a few small files:

    code        the library file holding the hot loop
    mbedtls.h   the headers it and its dependencies need, pruned
    lib.c       the other library files it links against
    harness.c   runs the benchmark.c call MBT_REPEAT times, prints a checksum

Dependencies are found by compiling every library file with the host compiler
and resolving symbols. Needs the `unifdef` tool.

    python3 -I benchmark/mbedtls/build.py [--repeat-json reps.json]
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
from amalgamate import amalgamate  # noqa: E402
from compact import prune, squeeze, strip_comments, unifdef  # noqa: E402

HERE = Path(__file__).resolve().parent
SRC = HERE / "src"

PRELUDE = r"""#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "mbedtls.h"

#ifndef MBT_REPEAT
#define MBT_REPEAT 1
#endif
#define BUFSIZE 16384

static unsigned char buf[BUFSIZE], tmp[200];

static int myrand(void *state, unsigned char *out, size_t len)
{
    (void) state;
    while (len--) *out++ = (unsigned char) rand();
    return 0;
}

static unsigned long fnv(const unsigned char *p, size_t n, unsigned long h)
{
    while (n--) h = (h ^ *p++) * 1099511628211UL;
    return h;
}

static void bench(void);

int main(void)
{
    srand(1);
    memset(buf, 0xAA, sizeof(buf));
    memset(tmp, 0xBB, sizeof(tmp));
    bench();
    printf("buf %016lx tmp %016lx\n", fnv(buf, sizeof(buf), 14695981039346656037UL),
           fnv(tmp, sizeof(tmp), 14695981039346656037UL));
    return 0;
}

#define LOOP for (int r_ = 0; r_ < MBT_REPEAT; r_++)
"""

KEYS3 = "for (int ks = 128; ks <= 256; ks += 64)"

# id -> (target library file, bench() body)
ITEMS = {
    "md5": ("md5.c", "LOOP mbedtls_md5(buf, BUFSIZE, tmp);"),
    "ripemd160": ("ripemd160.c", "LOOP mbedtls_ripemd160(buf, BUFSIZE, tmp);"),
    "sha1": ("sha1.c", "LOOP mbedtls_sha1(buf, BUFSIZE, tmp);"),
    "sha256": ("sha256.c", "LOOP mbedtls_sha256(buf, BUFSIZE, tmp, 0);"),
    "sha512": ("sha512.c", "LOOP mbedtls_sha512(buf, BUFSIZE, tmp, 0);"),
    "sha3_224": ("sha3.c", "LOOP mbedtls_sha3(MBEDTLS_SHA3_224, buf, BUFSIZE, tmp, 28);"),
    "sha3_256": ("sha3.c", "LOOP mbedtls_sha3(MBEDTLS_SHA3_256, buf, BUFSIZE, tmp, 32);"),
    "sha3_384": ("sha3.c", "LOOP mbedtls_sha3(MBEDTLS_SHA3_384, buf, BUFSIZE, tmp, 48);"),
    "sha3_512": ("sha3.c", "LOOP mbedtls_sha3(MBEDTLS_SHA3_512, buf, BUFSIZE, tmp, 64);"),
    "des3": ("des.c", """mbedtls_des3_context c; mbedtls_des3_init(&c);
    mbedtls_des3_set3key_enc(&c, tmp);
    LOOP mbedtls_des3_crypt_cbc(&c, MBEDTLS_DES_ENCRYPT, BUFSIZE, tmp, buf, buf);
    mbedtls_des3_free(&c);"""),
    "des": ("des.c", """mbedtls_des_context c; mbedtls_des_init(&c);
    mbedtls_des_setkey_enc(&c, tmp);
    LOOP mbedtls_des_crypt_cbc(&c, MBEDTLS_DES_ENCRYPT, BUFSIZE, tmp, buf, buf);
    mbedtls_des_free(&c);"""),
    "des3_cmac": ("des.c", """unsigned char out[8];
    const mbedtls_cipher_info_t *ci = mbedtls_cipher_info_from_type(MBEDTLS_CIPHER_DES_EDE3_ECB);
    LOOP { mbedtls_cipher_cmac(ci, tmp, 192, buf, BUFSIZE, out); buf[0] ^= out[0]; }"""),
    "aes_cbc": ("aes.c", f"""mbedtls_aes_context c; mbedtls_aes_init(&c);
    {KEYS3} {{ mbedtls_aes_setkey_enc(&c, tmp, ks);
        LOOP mbedtls_aes_crypt_cbc(&c, MBEDTLS_AES_ENCRYPT, BUFSIZE, tmp, buf, buf); }}
    mbedtls_aes_free(&c);"""),
    "aes_cfb128": ("aes.c", f"""mbedtls_aes_context c; mbedtls_aes_init(&c); size_t off = 0;
    {KEYS3} {{ mbedtls_aes_setkey_enc(&c, tmp, ks);
        LOOP mbedtls_aes_crypt_cfb128(&c, MBEDTLS_AES_ENCRYPT, BUFSIZE, &off, tmp, buf, buf); }}
    mbedtls_aes_free(&c);"""),
    "aes_cfb8": ("aes.c", f"""mbedtls_aes_context c; mbedtls_aes_init(&c);
    {KEYS3} {{ mbedtls_aes_setkey_enc(&c, tmp, ks);
        LOOP mbedtls_aes_crypt_cfb8(&c, MBEDTLS_AES_ENCRYPT, BUFSIZE, tmp, buf, buf); }}
    mbedtls_aes_free(&c);"""),
    "aes_ctr": ("aes.c", f"""mbedtls_aes_context c; mbedtls_aes_init(&c);
    unsigned char sb[16] = {{0}}; size_t off = 0;
    {KEYS3} {{ mbedtls_aes_setkey_enc(&c, tmp, ks);
        LOOP mbedtls_aes_crypt_ctr(&c, BUFSIZE, &off, tmp, sb, buf, buf); }}
    mbedtls_aes_free(&c);"""),
    "aes_xts": ("aes.c", """mbedtls_aes_xts_context c; mbedtls_aes_xts_init(&c);
    for (int ks = 128; ks <= 256; ks += 128) { mbedtls_aes_xts_setkey_enc(&c, tmp, ks * 2);
        LOOP mbedtls_aes_crypt_xts(&c, MBEDTLS_AES_ENCRYPT, BUFSIZE, tmp, buf, buf); }
    mbedtls_aes_xts_free(&c);"""),
    "aes_gcm": ("gcm.c", f"""mbedtls_gcm_context c; mbedtls_gcm_init(&c);
    {KEYS3} {{ mbedtls_gcm_setkey(&c, MBEDTLS_CIPHER_ID_AES, tmp, ks);
        LOOP mbedtls_gcm_crypt_and_tag(&c, MBEDTLS_GCM_ENCRYPT, BUFSIZE, tmp, 12, NULL, 0, buf, buf, 16, tmp); }}
    mbedtls_gcm_free(&c);"""),
    "aes_ccm": ("aes.c", f"""mbedtls_ccm_context c; mbedtls_ccm_init(&c);
    {KEYS3} {{ mbedtls_ccm_setkey(&c, MBEDTLS_CIPHER_ID_AES, tmp, ks);
        LOOP mbedtls_ccm_encrypt_and_tag(&c, BUFSIZE, tmp, 12, NULL, 0, buf, buf, tmp, 16); }}
    mbedtls_ccm_free(&c);"""),
    "aes_cmac": ("aes.c", """unsigned char out[16]; mbedtls_cipher_type_t t = MBEDTLS_CIPHER_AES_128_ECB;
    for (int ks = 128; ks <= 256; ks += 64, t++) {
        const mbedtls_cipher_info_t *ci = mbedtls_cipher_info_from_type(t);
        LOOP { mbedtls_cipher_cmac(ci, tmp, ks, buf, BUFSIZE, out); buf[0] ^= out[0]; } }
    LOOP { mbedtls_aes_cmac_prf_128(tmp, 16, buf, BUFSIZE, out); buf[1] ^= out[0]; }"""),
    "chachapoly": ("chacha20.c", """mbedtls_chachapoly_context c; mbedtls_chachapoly_init(&c);
    mbedtls_chachapoly_setkey(&c, tmp);
    LOOP mbedtls_chachapoly_encrypt_and_tag(&c, BUFSIZE, tmp, NULL, 0, buf, buf, tmp);
    mbedtls_chachapoly_free(&c);"""),
    "aria": ("aria.c", f"""mbedtls_aria_context c; mbedtls_aria_init(&c);
    {KEYS3} {{ mbedtls_aria_setkey_enc(&c, tmp, ks);
        LOOP mbedtls_aria_crypt_cbc(&c, MBEDTLS_ARIA_ENCRYPT, BUFSIZE, tmp, buf, buf); }}
    mbedtls_aria_free(&c);"""),
    "camellia": ("camellia.c", f"""mbedtls_camellia_context c; mbedtls_camellia_init(&c);
    {KEYS3} {{ mbedtls_camellia_setkey_enc(&c, tmp, ks);
        LOOP mbedtls_camellia_crypt_cbc(&c, MBEDTLS_CAMELLIA_ENCRYPT, BUFSIZE, tmp, buf, buf); }}
    mbedtls_camellia_free(&c);"""),
    "chacha20": ("chacha20.c", "LOOP mbedtls_chacha20_crypt(buf, buf, 0U, BUFSIZE, buf, buf);"),
    "poly1305": ("poly1305.c", "LOOP mbedtls_poly1305_mac(buf, buf, BUFSIZE, buf);"),
    "ctr_drbg": ("aes.c", """mbedtls_ctr_drbg_context c;
    for (int pr = 0; pr < 2; pr++) { mbedtls_ctr_drbg_init(&c);
        mbedtls_ctr_drbg_seed(&c, myrand, NULL, NULL, 0);
        if (pr) mbedtls_ctr_drbg_set_prediction_resistance(&c, MBEDTLS_CTR_DRBG_PR_ON);
        LOOP for (int o = 0; o < BUFSIZE; o += 1024) mbedtls_ctr_drbg_random(&c, buf + o, 1024);
        mbedtls_ctr_drbg_free(&c); }"""),
    "hmac_drbg": ("sha256.c", """mbedtls_hmac_drbg_context c;
    mbedtls_md_type_t mds[2] = { MBEDTLS_MD_SHA1, MBEDTLS_MD_SHA256 };
    for (int m = 0; m < 2; m++) for (int pr = 0; pr < 2; pr++) { mbedtls_hmac_drbg_init(&c);
        mbedtls_hmac_drbg_seed(&c, mbedtls_md_info_from_type(mds[m]), myrand, NULL, NULL, 0);
        if (pr) mbedtls_hmac_drbg_set_prediction_resistance(&c, MBEDTLS_HMAC_DRBG_PR_ON);
        LOOP for (int o = 0; o < BUFSIZE; o += 1024) mbedtls_hmac_drbg_random(&c, buf + o, 1024);
        mbedtls_hmac_drbg_free(&c); }"""),
    "rsa": ("bignum_core.c", """mbedtls_rsa_context c; mbedtls_rsa_init(&c);
    mbedtls_rsa_gen_key(&c, myrand, NULL, 2048, 65537);
    LOOP { buf[0] = 0; mbedtls_rsa_public(&c, buf, buf);
           buf[0] = 0; mbedtls_rsa_private(&c, myrand, NULL, buf, buf); }
    mbedtls_rsa_free(&c);"""),
    "dhm": ("bignum_core.c", """static const unsigned char P[] = MBEDTLS_DHM_RFC3526_MODP_2048_P_BIN;
    static const unsigned char G[] = MBEDTLS_DHM_RFC3526_MODP_2048_G_BIN;
    mbedtls_dhm_context c; mbedtls_mpi p, g; size_t olen, n;
    mbedtls_dhm_init(&c); mbedtls_mpi_init(&p); mbedtls_mpi_init(&g);
    mbedtls_mpi_read_binary(&p, P, sizeof(P)); mbedtls_mpi_read_binary(&g, G, sizeof(G));
    mbedtls_dhm_set_group(&c, &p, &g); n = mbedtls_dhm_get_len(&c);
    mbedtls_dhm_make_public(&c, (int) n, buf, n, myrand, NULL);
    mbedtls_dhm_read_public(&c, buf, n);
    LOOP { mbedtls_dhm_make_public(&c, (int) n, buf, n, myrand, NULL);
           mbedtls_dhm_calc_secret(&c, buf, sizeof(buf), &olen, myrand, NULL); }
    mbedtls_dhm_free(&c); mbedtls_mpi_free(&p); mbedtls_mpi_free(&g);"""),
    "ecdsa": ("ecp.c", """mbedtls_ecdsa_context c; size_t sl; memset(buf, 0x2A, sizeof(buf));
    mbedtls_ecdsa_init(&c); mbedtls_ecdsa_genkey(&c, MBEDTLS_ECP_DP_SECP256R1, myrand, NULL);
    LOOP { mbedtls_ecdsa_write_signature(&c, MBEDTLS_MD_SHA256, buf, 32, tmp, sizeof(tmp), &sl, myrand, NULL);
           mbedtls_ecdsa_read_signature(&c, buf, 32, tmp, sl); }
    mbedtls_ecdsa_free(&c);"""),
    "ecdh": ("ecp.c", """mbedtls_ecdh_context s, cl; static unsigned char bs[BUFSIZE], bc[BUFSIZE];
    size_t pl, publ, secl;
    mbedtls_ecdh_init(&s); mbedtls_ecdh_setup(&s, MBEDTLS_ECP_DP_SECP256R1);
    mbedtls_ecdh_make_params(&s, &pl, bs, sizeof(bs), myrand, NULL);
    LOOP { const unsigned char *p = bs; mbedtls_ecdh_init(&cl);
           mbedtls_ecdh_read_params(&cl, &p, p + pl);
           mbedtls_ecdh_make_public(&cl, &publ, bc, sizeof(bc), myrand, NULL);
           mbedtls_ecdh_calc_secret(&cl, &secl, bc, sizeof(bc), myrand, NULL);
           buf[r_ % BUFSIZE] ^= bc[0]; mbedtls_ecdh_free(&cl); }
    mbedtls_ecdh_free(&s);"""),
}


CBC = ["MBEDTLS_CIPHER_MODE_CBC"]
AES = ["MBEDTLS_AES_C", "MBEDTLS_CIPHER_MODE_CBC", "MBEDTLS_CIPHER_MODE_CFB", "MBEDTLS_CIPHER_MODE_CTR",
       "MBEDTLS_CIPHER_MODE_XTS"]
SHA3 = ["MBEDTLS_SHA3_C"]
P256 = ["MBEDTLS_BIGNUM_C", "MBEDTLS_ECP_C", "MBEDTLS_ECP_DP_SECP256R1_ENABLED", "MBEDTLS_ECP_NIST_OPTIM"]
# id -> the configuration options the row is built with (everything else is off).
CONFIG = {
    "md5": ["MBEDTLS_MD5_C"],
    "ripemd160": ["MBEDTLS_RIPEMD160_C"],
    "sha1": ["MBEDTLS_SHA1_C"],
    "sha256": ["MBEDTLS_SHA256_C", "MBEDTLS_SHA224_C"],
    "sha512": ["MBEDTLS_SHA512_C", "MBEDTLS_SHA384_C"],
    "sha3_224": SHA3, "sha3_256": SHA3, "sha3_384": SHA3, "sha3_512": SHA3,
    "des3": ["MBEDTLS_DES_C"] + CBC,
    "des": ["MBEDTLS_DES_C"] + CBC,
    "des3_cmac": ["MBEDTLS_DES_C", "MBEDTLS_CIPHER_C", "MBEDTLS_CMAC_C"],
    "aes_cbc": AES, "aes_cfb128": AES, "aes_cfb8": AES, "aes_ctr": AES, "aes_xts": AES,
    "aes_gcm": ["MBEDTLS_AES_C", "MBEDTLS_GCM_C"],
    "aes_ccm": ["MBEDTLS_AES_C", "MBEDTLS_CCM_C"],
    "aes_cmac": ["MBEDTLS_AES_C", "MBEDTLS_CIPHER_C", "MBEDTLS_CMAC_C"],
    "chachapoly": ["MBEDTLS_CHACHA20_C", "MBEDTLS_POLY1305_C", "MBEDTLS_CHACHAPOLY_C"],
    "aria": ["MBEDTLS_ARIA_C"] + CBC,
    "camellia": ["MBEDTLS_CAMELLIA_C"] + CBC,
    "chacha20": ["MBEDTLS_CHACHA20_C"],
    "poly1305": ["MBEDTLS_POLY1305_C"],
    "ctr_drbg": ["MBEDTLS_AES_C", "MBEDTLS_CTR_DRBG_C"],
    "hmac_drbg": ["MBEDTLS_MD_C", "MBEDTLS_SHA1_C", "MBEDTLS_SHA256_C", "MBEDTLS_HMAC_DRBG_C"],
    "rsa": ["MBEDTLS_BIGNUM_C", "MBEDTLS_RSA_C", "MBEDTLS_GENPRIME", "MBEDTLS_PKCS1_V15", "MBEDTLS_OID_C"],
    "dhm": ["MBEDTLS_BIGNUM_C", "MBEDTLS_DHM_C"],
    "ecdsa": P256 + ["MBEDTLS_ECDSA_C", "MBEDTLS_ASN1_PARSE_C", "MBEDTLS_ASN1_WRITE_C", "MBEDTLS_MD_C",
                     "MBEDTLS_SHA256_C"],
    "ecdh": P256 + ["MBEDTLS_ECDH_C"],
}
# Rows larger than this (code + supporting files) are left out: each row
# should stay small and fast to build (drops the RSA / ECC bignum stacks).
MAX_LINES = 6000
# Platform macros of other targets; their #if branches are dropped.
FOREIGN = ["__aarch64__", "__arm__", "__ARM_NEON", "__ARM_ARCH", "__thumb__", "__thumb2__", "__x86_64__", "__i386__",
           "__amd64__", "_M_X64", "_M_IX86", "_M_AMD64", "_M_ARM64", "_MSC_VER", "__ARMCC_VERSION", "__ICCARM__",
           "__IAR_SYSTEMS_ICC__", "_WIN32", "_WIN64", "__CC_ARM", "__TINYC__", "__mips__", "__ppc__", "__powerpc__",
           "__s390x__", "__APPLE__", "_M_ARM", "_M_ARMT", "_X86_", "_M_I86", "_M_ARM64EC", "__MINGW32__",
           "__INTEL_COMPILER", "UINT_UNALIGNED", "UINT_UNALIGNED_STRUCT", "MBEDTLS_POP_IAR_LANGUAGE_PRAGMA", "__ARM_FEATURE_CRYPTO", "__ARM_FEATURE_AES", "__ARM_FEATURE_SHA2",
           "__ARM_FEATURE_SHA3", "__ARM_FEATURE_SHA512", "__ARM_FEATURE_UNALIGNED", "__COVERITY__", "__xtensa__",
           "MBEDTLS_HAVE_ASM", "MBEDTLS_TEST_HOOKS", "MBEDTLS_PLATFORM_C", "MBEDTLS_THREADING_C",
           "MBEDTLS_SELF_TEST", "MBEDTLS_DEPRECATED_REMOVED", "MBEDTLS_DEPRECATED_WARNING",
           "MBEDTLS_CHECK_RETURN_TYPICAL", "MBEDTLS_USER_CONFIG_FILE", "MBEDTLS_PSA_CRYPTO_CONFIG_FILE",
           "MBEDTLS_PSA_CRYPTO_USER_CONFIG_FILE", "MBEDTLS_CONFIG_FILE",
           # set inside module headers, never under these configurations
           "MBEDTLS_CTR_DRBG_USE_PSA_CRYPTO", "MBEDTLS_AESCE_HAS_SUPPORT", "MBEDTLS_AESCE_HAVE_CODE",
           "MBEDTLS_AESNI_HAVE_CODE", "MBEDTLS_AESNI_HAVE_INTRINSICS", "MBEDTLS_AESNI_AES", "MBEDTLS_AESNI_CLMUL",
           "MBEDTLS_VIA_PADLOCK_HAVE_CODE", "MBEDTLS_PADLOCK_C", "MBEDTLS_HAVE_NEON_INTRINSICS", "MBEDTLS_CT_ARM_ASM",
           "MBEDTLS_CT_X86_64_ASM", "MBEDTLS_CT_X86_ASM", "MBEDTLS_ARCH_IS_ARM32", "MBEDTLS_ARCH_IS_ARM64",
           "MBEDTLS_ARCH_IS_ARMV8_A", "MBEDTLS_ARCH_IS_X86", "MBEDTLS_ARCH_IS_X64", "MBEDTLS_PLATFORM_IS_WINDOWS_ON_ARM64"]
# Byte-order helpers kept in mbedtls.h even when the original file does not use
# them (optimized versions commonly do).
KEEP = (" MBEDTLS_GET_UINT32_BE MBEDTLS_PUT_UINT32_BE MBEDTLS_GET_UINT32_LE MBEDTLS_PUT_UINT32_LE"
        " MBEDTLS_GET_UINT64_BE MBEDTLS_PUT_UINT64_BE MBEDTLS_GET_UINT64_LE MBEDTLS_PUT_UINT64_LE"
        " MBEDTLS_BSWAP32 MBEDTLS_BSWAP64 MBEDTLS_BYTE_0 mbedtls_get_unaligned_uint32"
        " mbedtls_put_unaligned_uint32 mbedtls_get_unaligned_uint64 mbedtls_put_unaligned_uint64 ")

# Set part-way through build_info.h to check include order. The one check made
# before they are set is dropped (ORDER_CHECK); everywhere else they count as set.
ORDER = {"MBEDTLS_CONFIG_FILES_READ", "MBEDTLS_CONFIG_IS_FINALIZED"}
ORDER_CHECK = re.compile(r"#if defined\((MBEDTLS_CONFIG_FILES_READ|MBEDTLS_CONFIG_IS_FINALIZED)\)\n#error[^\n]*\n(?:[^\n]*\n)??#endif\n")

DEF_RE = re.compile(r"^[0-9a-f]+ [TDBSRC] _?(\w+)$")
UND_RE = re.compile(r"^\s+U _?(\w+)$")
QINC_RE = re.compile(r'^[ \t]*#[ \t]*include[ \t]*(?:"([^"]+)"|<((?:mbedtls|psa)/[^>]+)>)[^\n]*\n', re.M)
COND_RE = re.compile(r"^[ \t]*#[ \t]*(?:if|ifdef|ifndef|elif)\b((?:\\\n|[^\n])*)", re.M)
DEFINE_RE = re.compile(r"^[ \t]*#[ \t]*define[ \t]+(\w+)", re.M)
MACRO_RE = re.compile(r"^[ \t]*#[ \t]*define[ \t]+(\w+)(?:\\\n|[^\n])*\n", re.M)


def symbols(cc: str, path: Path, obj: Path, flags: list[str]) -> tuple[set, set]:
    subprocess.run([cc, "-c", "-O0", "-w", *flags, str(path), "-o", str(obj)], check=True)
    out = subprocess.run(["nm", str(obj)], check=True, capture_output=True, text=True).stdout
    defs, undef = set(), set()
    for line in out.splitlines():
        if m := DEF_RE.match(line):
            defs.add(m.group(1))
        elif m := UND_RE.match(line):
            undef.add(m.group(1))
    return defs, undef


def closure(start_undef: set, table: dict, skip: str) -> list[str]:
    owner = {}
    for name, (defs, _) in table.items():
        for s in defs:
            owner.setdefault(s, name)
    need, done, todo = set(), set(), set(start_undef)
    while todo:
        s = todo.pop()
        if s in done:
            continue
        done.add(s)
        f = owner.get(s)
        if f is None or f in need:
            continue
        need.add(f)
        if f != skip:
            todo |= table[f][1]
    need.discard(skip)
    return sorted(need)


def config_macros(cc: str, flags: list[str]) -> dict[str, str | None]:
    """Macros set by the configuration (mbedtls_config.h plus the adjust headers)."""
    out = subprocess.run([cc, "-E", "-dM", *flags, "-x", "c", "-"], input='#include "mbedtls/build_info.h"\n',
                         check=True, capture_output=True, text=True).stdout
    res = {}
    for m in re.finditer(r"^#define (\w+)(?:\(.*?\))?(?: (.*))?$", out, re.M):
        name, val = m.group(1), (m.group(2) or "").strip()
        if not re.match(r"(MBEDTLS|PSA)_", name) or name.endswith("_H") or "(" in m.group(0).split()[1]:
            continue
        if val == "" or re.fullmatch(r"\(?-?\d+[uUlL]*\)?", val):
            res[name] = val.strip("()").rstrip("uUlL") or None
    return res


def prune_macros(text: str, users: str) -> str:
    """Drop #defines whose name is used nowhere else."""
    while True:
        changed = False
        for m in list(MACRO_RE.finditer(text))[::-1]:
            name = m.group(1)
            rest = text[:m.start()] + text[m.end():]
            if not re.search(r"\b" + name + r"\b", rest + users):
                text, changed = rest, True
        if not changed:
            return text


def resolve(text: str, cfg: dict, keep: set) -> str:
    """unifdef every configuration / foreign-platform condition in text."""
    names = set()
    for cond in COND_RE.findall(text):
        names |= set(re.findall(r"\b((?:MBEDTLS|PSA)_\w+|__\w+__|_M_\w+|_MSC_VER|_WIN\d\d)\b", cond))
    undef = [n for n in sorted(names) if n not in cfg and n not in keep and re.match(r"(MBEDTLS|PSA)_", n)
             and not n.endswith("_H")] + FOREIGN
    # unifdef does not follow backslash continuations: join #if lines first.
    text = re.sub(r"^[ \t]*#[ \t]*(?:if|elif)\b(?:[^\n]*\\\n)+[^\n]*",
                  lambda m: re.sub(r"\s*\\\n\s*", " ", m.group(0)), strip_comments(text), flags=re.M)
    text = ORDER_CHECK.sub("", text)
    return squeeze(unifdef(text, cfg, sorted(set(undef) - set(cfg))))


def project_includes(text: str) -> str:
    return QINC_RE.sub("", text)


def build_row(pid: str, target: str, body: str, cc: str, lib_files: list[Path], reps: dict) -> dict:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        cfg_text = "".join(f"#define {m}\n" for m in CONFIG[pid])
        (td / "cfg.h").write_text(cfg_text)
        flags = [f"-I{td}", f"-I{SRC / 'include'}", f"-I{SRC / 'library'}", '-DMBEDTLS_CONFIG_FILE="cfg.h"']
        cfg = config_macros(cc, flags)
        with ThreadPoolExecutor(8) as pool:
            table = dict(zip([p.name for p in lib_files],
                             pool.map(lambda p: symbols(cc, p, td / (p.stem + ".o"), flags), lib_files)))
        orig_prelude = PRELUDE.replace('#include "mbedtls.h"\n', "".join(
            f'#include "mbedtls/{h.name}"\n' for h in sorted((SRC / "include/mbedtls").glob("*.h"))
            if not re.search(r"config|check_|_internal|compat", h.name)))
        harness = PRELUDE + "\nstatic void bench(void)\n{\n    " + body + "\n}\n"
        (td / "h.c").write_text(orig_prelude + "\nstatic void bench(void)\n{\n    " + body + "\n}\n")
        _, hund = symbols(cc, td / "h.c", td / "h.o", flags)
        deps = closure(hund | table[target][1], table, target)
    # Every project header the row's sources include, inlined once, in order.
    srcs = [target] + deps
    texts = {f: (SRC / "library" / f).read_text(encoding="latin-1") for f in srcs}
    incs = "".join(f'#include "{h}"\n' for h in dict.fromkeys(
        a or b for t in texts.values() for a, b in QINC_RE.findall(t)) if not h.endswith(".c"))
    hdr = amalgamate([("mbedtls.h", '#include "common.h"\n' + incs)], [SRC / "include", SRC / "library"],
                     {"mbedtls/mbedtls_config.h": cfg_text}, angle=True)
    # Macros the configuration step may set are resolved from cfg; other macros
    # #defined in the sources (helpers, defaults behind #ifndef) are left alone.
    conf = amalgamate([("c.h", '#include "mbedtls/build_info.h"\n')], [SRC / "include"],
                      {"mbedtls/mbedtls_config.h": (SRC / "include/mbedtls/mbedtls_config.h").read_text()}, angle=True)
    conf_names = set(DEFINE_RE.findall(conf)) | set(re.findall(r"^//#define (\w+)[ \t]*$", conf, re.M))
    keep = (set(DEFINE_RE.findall(hdr)) | set(n for t in texts.values() for n in DEFINE_RE.findall(t))) - conf_names
    hdr = amalgamate([("mbedtls.h", '#include "common.h"\n' + incs)], [SRC / "include", SRC / "library"],
                     {"mbedtls/mbedtls_config.h": cfg_text}, angle=True, transform=lambda t: resolve(t, cfg, keep))
    hdr = re.sub(r"(?m)^#include (MBEDTLS_\w+)\n", "", squeeze(hdr))
    code = '#include "mbedtls.h"\n' + project_includes(resolve(texts[target], cfg, keep))
    libc = "".join(f"/* ---- {d} ---- */\n" + project_includes(resolve(texts[d], cfg, keep)) for d in deps)
    hdr = squeeze(prune_macros(prune(hdr, code + libc + harness + KEEP), code + libc + harness + KEEP))
    files = {"mbedtls.h": hdr, "harness.c": harness}
    if libc.strip():
        files["lib.c"] = '#include "mbedtls.h"\n' + libc
    return {
        "id": f"mbedtls/{pid}",
        "suite": "mbedtls",
        "extension": "b",
        "target_file": target,
        "code": code,
        "files": files,
        "compile_sources": [k for k in ("harness.c", "lib.c") if k in files],
        "compile_defs": f"-w -DMBT_REPEAT={int(reps.get(pid, 1))}",
        "output_filter": "",
        "preserve_functions": [],
        "required_functions": [],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cc", default="cc")
    ap.add_argument("--repeat-json", default=str(HERE / "repeat.json"))
    ap.add_argument("--output", default=str(HERE / "dataset.jsonl"))
    ap.add_argument("--only", help="comma-separated ids")
    args = ap.parse_args()
    reps = json.loads(Path(args.repeat_json).read_text()) if args.repeat_json else {}
    lib_files = sorted((SRC / "library").glob("*.c"))
    only = set(args.only.split(",")) if args.only else None
    todo = [(pid, t, b) for pid, (t, b) in ITEMS.items() if not only or pid in only]
    with ThreadPoolExecutor(8) as pool:
        rows = list(pool.map(lambda x: build_row(*x, args.cc, lib_files, reps), todo))
    for r in [r for r in rows if r["code"].count("\n") + sum(v.count("\n") for v in r["files"].values()) > MAX_LINES]:
        print("skip (too large):", r["id"])
        rows.remove(r)
    # Keep only the programs listed for this suite in classes.json.
    tasked = set().union(*json.loads((HERE.parent / "classes.json").read_text())["mbedtls"].values())
    rows = [r for r in rows if r["id"] in tasked]
    with open(args.output, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
