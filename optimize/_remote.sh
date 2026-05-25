#!/bin/sh
set -u
ulimit -c 0 2>/dev/null || true

RESULT_PATH="${1:-result.json}"

: "${FLOAT_TOLERANCE:=0.01}"
: "${FLOAT_REL_TOLERANCE:=1e-4}"

write_bootstrap_fail_result() {
  message="$1"
  printf '{"pid":"","status":"fail","stage":"exec","error_type":"bootstrap","message":"%s","global_sf_n":null,"baseline_time_ms":0.0,"optimized_time_ms":0.0,"speedup_ratio":0.0,"baseline_times_ms":[],"optimized_times_ms":[],"cases":[]}\n' "$message" > "$RESULT_PATH"
}

if [ ! -f "./runner_config.sh" ]; then
  write_bootstrap_fail_result "missing runner_config.sh"
  exit 0
fi

. ./runner_config.sh
OUTPUT_LIMIT_BYTES="${OUTPUT_LIMIT_BYTES:-10485760}"
OUTPUT_LIMIT_BLOCKS="$(( (OUTPUT_LIMIT_BYTES + 511) / 512 ))"
REMOTE_NICE="${REMOTE_NICE:-10}"

json_escape_file() {
  if [ ! -f "$1" ]; then
    return 0
  fi
  sed ':a;N;$!ba;s/\\/\\\\/g;s/"/\\"/g;s/\r//g;s/\n/\\n/g' "$1"
}

json_escape_text() {
  printf '%s' "$1" | sed ':a;N;$!ba;s/\\/\\\\/g;s/"/\\"/g;s/\r//g;s/\n/\\n/g'
}

now_ms() {
  ns="$(date +%s%N 2>/dev/null || true)"
  case "$ns" in
    *N*|"")
      sec="$(date +%s)"
      awk "BEGIN { printf \"%.3f\", $sec * 1000 }"
      ;;
    *)
      awk "BEGIN { printf \"%.3f\", $ns / 1000000 }"
      ;;
  esac
}

mean_csv() {
  awk -F, '{
    sum = 0;
    count = 0;
    for (i = 1; i <= NF; i++) {
      if ($i != "") {
        sum += $i;
        count += 1;
      }
    }
    if (count == 0) printf "0.000000";
    else printf "%.6f", sum / count;
  }'
}

run_with_timeout() {
  timeout_sec="$1"
  shift
  if command -v timeout >/dev/null 2>&1; then
    timeout "$timeout_sec" "$@"
  else
    "$@"
  fi
}

write_excerpt_file() {
  src="$1"
  dst="$2"
  max_chars="${3:-600}"
  : > "$dst"
  if [ ! -f "$src" ]; then
    return 0
  fi
  LC_ALL=C head -c "$max_chars" "$src" > "$dst"
  total_chars="$(wc -c < "$src" | tr -d '[:space:]')"
  if [ "${total_chars:-0}" -gt "$max_chars" ]; then
    printf '\n...[truncated]...' >> "$dst"
  fi
}

normalize_to_file() {
  src="$1"
  dst="$2"
  if [ ! -f "$src" ]; then
    : > "$dst"
    return 0
  fi
  sed 's/[[:space:]]*$//' "$src" > "$dst"
}

is_float_text() {
  printf '%s' "$1" | grep -Eq '^-?[0-9]+([.][0-9]*)?([eE][-+]?[0-9]+)?$|^-?[.][0-9]+([eE][-+]?[0-9]+)?$'
}

compare_outputs() {
  expected_file="$1"
  actual_file="$2"
  message_file="$3"
  expected_norm="$message_file.expected.norm"
  actual_norm="$message_file.actual.norm"

  normalize_to_file "$expected_file" "$expected_norm"
  normalize_to_file "$actual_file" "$actual_norm"

  # Reject saturated floats. inf/nan in either side means the kernel went numerically
  # unstable; identical "inf" strings on both sides is not a real correctness signal
  # because any optimization that touches even one element will also produce inf and
  # match by string. Force a fail so such samples are excluded from speedup ratios.
  if LC_ALL=C grep -Eq -i '(^|[^a-z0-9_])(inf|infinity|nan)([^a-z0-9_]|$)' "$expected_norm" "$actual_norm"; then
    printf 'baseline or optimized output contains inf/nan; treated as numerically unstable\n' > "$message_file"
    rm -f "$expected_norm" "$actual_norm"
    return 1
  fi

  awk -v tol="$FLOAT_TOLERANCE" -v rtol="$FLOAT_REL_TOLERANCE" -v msg_file="$message_file" '
    function is_num(s) {
      return (s ~ /^[+-]?([0-9]+|[0-9]*\.[0-9]+|[0-9]+\.)([eE][-+]?[0-9]+)?$/);
    }
    function abs(x) { return x < 0 ? -x : x; }
    NR == FNR {
      for (i = 1; i <= NF; i++) { exp_tok[++ne] = $i }
      next
    }
    {
      for (i = 1; i <= NF; i++) { act_tok[++na] = $i }
    }
    END {
      if (ne != na) {
        printf "token count mismatch: expected %d tokens, got %d\n", ne, na > msg_file;
        exit 1;
      }
      mismatches = 0;
      for (i = 1; i <= ne; i++) {
        e = exp_tok[i]; a = act_tok[i];
        if (is_num(e) && is_num(a)) {
          ev = e + 0; av = a + 0;
          diff = abs(ev - av);
          magn = abs(ev); am = abs(av);
          if (am > magn) magn = am;
          if (diff <= tol) continue;
          if (magn > 0 && diff / magn <= rtol) continue;
          mismatches++;
          if (mismatches <= 3) {
            printf "float mismatch at token %d: expected %s, got %s (abs %.6g, rel %.6g)\n", i, e, a, diff, (magn > 0 ? diff/magn : 0) > msg_file;
          }
        } else {
          if (e != a) {
            mismatches++;
            if (mismatches <= 3) {
              printf "token mismatch at position %d: expected \"%s\", got \"%s\"\n", i, e, a > msg_file;
            }
          }
        }
      }
      if (mismatches > 0) {
        printf "total mismatches: %d / %d tokens\n", mismatches, ne > msg_file;
        exit 1;
      }
      print "pass" > msg_file;
      exit 0;
    }
  ' "$expected_norm" "$actual_norm"
  rc="$?"
  rm -f "$expected_norm" "$actual_norm"
  return "$rc"
}

build_runtime_message() {
  err_file="$1"
  out_file="$2"
  message_file="$3"
  if [ -f "$out_file" ]; then
    out_bytes="$(wc -c < "$out_file" | tr -d '[:space:]')"
    if [ "${out_bytes:-0}" -ge "${OUTPUT_LIMIT_BYTES:-10485760}" ]; then
      printf 'output exceeded limit of %s bytes' "$OUTPUT_LIMIT_BYTES" > "$message_file"
      return 0
    fi
  fi
  printf 'process exited with non-zero status' > "$message_file"
}

build_wrong_answer_message() {
  compare_file="$1"
  expected_file="$2"
  actual_file="$3"
  message_file="$4"
  if [ -f "$compare_file" ]; then
    cat "$compare_file" > "$message_file"
  else
    printf 'output mismatch' > "$message_file"
  fi
}

write_fail_result() {
  stage="$1"
  error_type="$2"
  message_file="$3"
  cases_json="${4:-[]}"
  excerpt_file="$message_file.excerpt"
  write_excerpt_file "$message_file" "$excerpt_file" 800
  msg="$(json_escape_file "$excerpt_file")"
  rm -f "$excerpt_file"
  cat > "$RESULT_PATH" <<EOF
{"pid":"$(json_escape_text "$PID")","status":"fail","stage":"$stage","error_type":"$error_type","message":"$msg","global_sf_n":$GLOBAL_SF_N,"baseline_time_ms":0.0,"optimized_time_ms":0.0,"speedup_ratio":0.0,"baseline_times_ms":[],"optimized_times_ms":[],"cases":$cases_json}
EOF
}

compile_one() {
  src="$1"
  bin="$2"
  err="$3"
  if command -v timeout >/dev/null 2>&1; then
    sh -c "timeout '$COMPILE_TIMEOUT' nice -n '$REMOTE_NICE' $COMPILE_CMD '$src' -o '$bin' ${COMPILE_TAIL:-}" 2> "$err"
  else
    sh -c "nice -n '$REMOTE_NICE' $COMPILE_CMD '$src' -o '$bin' ${COMPILE_TAIL:-}" 2> "$err"
  fi
}

compile_baseline_one() {
  src="$1"
  bin="$2"
  err="$3"
  cache_root="${BASELINE_CACHE_ROOT:-/tmp/rv_opt_baseline_cache}"

  # Cache key must hash every input that affects baseline.bin: the source itself,
  # the compile command, AND every shared support file pulled in by COMPILE_CMD
  # (common.c, common.h, array_defs.h, dummy.c, globals.c). Hashing only "$src"
  # makes the cache reuse a stale binary whenever harness files change.
  cache_inputs="$src"
  for f in common.c common.h array_defs.h dummy.c globals.c; do
    [ -f "$f" ] && cache_inputs="$cache_inputs $f"
  done
  if command -v sha256sum >/dev/null 2>&1; then
    cache_key="$( (printf '%s\n' "$COMPILE_CMD ${COMPILE_TAIL:-}"; for f in $cache_inputs; do cat "$f"; done) | sha256sum | awk '{print $1}' )"
  else
    cache_key="$( (printf '%s\n' "$COMPILE_CMD ${COMPILE_TAIL:-}"; for f in $cache_inputs; do cat "$f"; done) | cksum | awk '{print $1 "_" $2}' )"
  fi
  cache_bin="$cache_root/$cache_key.bin"

  if [ -x "$cache_bin" ]; then
    cp "$cache_bin" "$bin"
    chmod +x "$bin" 2>/dev/null || true
    : > "$err"
    return 0
  fi

  mkdir -p "$cache_root" 2>/dev/null || true
  compile_one "$src" "$bin" "$err"
  rc="$?"
  if [ "$rc" -eq 0 ] && [ -x "$bin" ] && [ -d "$cache_root" ]; then
    tmp_cache="$cache_bin.$$"
    cp "$bin" "$tmp_cache" 2>/dev/null && chmod +x "$tmp_cache" 2>/dev/null && mv "$tmp_cache" "$cache_bin" 2>/dev/null || rm -f "$tmp_cache"
  fi
  return "$rc"
}

case "${REMOTE_WALL_GUARD:-0}" in
  1)
    ;;
  *)
    case "${WALL_TIMEOUT:-0}" in
      ''|*[!0-9]*)
        ;;
      *)
        if [ "${WALL_TIMEOUT}" -gt 0 ] && command -v timeout >/dev/null 2>&1; then
          export REMOTE_WALL_GUARD=1
          exec timeout "${WALL_TIMEOUT}" /bin/sh "$0" "$@"
        fi
        ;;
    esac
    ;;
esac

compile_baseline_one baseline.cpp ./baseline.bin baseline.compile.err
baseline_compile_rc="$?"
if [ "$baseline_compile_rc" -ne 0 ]; then
  write_fail_result "compile" "baseline_compile" baseline.compile.err
  exit 0
fi

compile_one optimized.cpp ./optimized.bin optimized.compile.err
optimized_compile_rc="$?"
if [ "$optimized_compile_rc" -ne 0 ]; then
  write_fail_result "compile" "optimized_compile" optimized.compile.err
  exit 0
fi

correct_cases_json="["
first_case=1
baseline_times_csv=""
optimized_times_csv=""
while IFS="$(printf '\t')" read -r testcase_index input_file; do
  [ -z "${testcase_index:-}" ] && continue

  run_case() {
    bin_path="$1"
    input_path="$2"
    prefix="$3"
    start_ms="$(now_ms)"
    if [ "${OUTPUT_LIMIT_BLOCKS:-0}" -gt 0 ]; then
      run_with_timeout "$RUN_TIMEOUT" sh -c '
        ulimit -c 0 2>/dev/null || true
        ulimit -f "$1" 2>/dev/null || true
        exec nice -n "$5" "$2" < "$3" > "$4.out" 2> "$4.err"
      ' sh "$OUTPUT_LIMIT_BLOCKS" "$bin_path" "$input_path" "$prefix" "$REMOTE_NICE"
    else
      run_with_timeout "$RUN_TIMEOUT" nice -n "$REMOTE_NICE" "$bin_path" < "$input_path" > "$prefix.out" 2> "$prefix.err"
    fi
    rc="$?"
    end_ms="$(now_ms)"
    awk "BEGIN { printf \"%.6f\", $end_ms - $start_ms }" > "$prefix.time"
    printf '%s' "$rc" > "$prefix.rc"
  }

  run_case ./baseline.bin "$input_file" "correct.baseline.$testcase_index"
  run_case ./optimized.bin "$input_file" "correct.optimized.$testcase_index"

  brc="$(cat "correct.baseline.$testcase_index.rc")"
  orc="$(cat "correct.optimized.$testcase_index.rc")"
  btime="$(cat "correct.baseline.$testcase_index.time")"
  otime="$(cat "correct.optimized.$testcase_index.time")"

  output_match=false
  case_message_file="correct.case.$testcase_index.message"
  compare_message_file="correct.compare.$testcase_index.msg"
  : > "$case_message_file"
  error_type=""

  if [ "$brc" -ne 0 ]; then
    build_runtime_message \
      "correct.baseline.$testcase_index.err" \
      "correct.baseline.$testcase_index.out" \
      "$case_message_file"
    error_type="baseline_runtime"
  elif [ "$orc" -ne 0 ]; then
    build_runtime_message \
      "correct.optimized.$testcase_index.err" \
      "correct.optimized.$testcase_index.out" \
      "$case_message_file"
    error_type="optimized_runtime"
  else
    baseline_compare_input="correct.baseline.$testcase_index.out"
    optimized_compare_input="correct.optimized.$testcase_index.out"
    if [ "${MERGE_STDERR:-0}" = "1" ]; then
      baseline_compare_input="correct.baseline.$testcase_index.merged"
      optimized_compare_input="correct.optimized.$testcase_index.merged"
      cat "correct.baseline.$testcase_index.out" "correct.baseline.$testcase_index.err" > "$baseline_compare_input"
      cat "correct.optimized.$testcase_index.out" "correct.optimized.$testcase_index.err" > "$optimized_compare_input"
    fi
    if compare_outputs \
      "$baseline_compare_input" \
      "$optimized_compare_input" \
      "$compare_message_file"
    then
      output_match=true
      : > "$case_message_file"
    else
      build_wrong_answer_message \
        "$compare_message_file" \
        "$baseline_compare_input" \
        "$optimized_compare_input" \
        "$case_message_file"
      error_type="wrong_answer"
    fi
  fi

  case_msg="$(json_escape_file "$case_message_file")"
  case_json="{\"testcase_index\":$testcase_index,\"baseline_returncode\":$brc,\"optimized_returncode\":$orc,\"baseline_time_ms\":$btime,\"optimized_time_ms\":$otime,\"output_match\":$output_match,\"message\":\"$case_msg\"}"
  rm -f "$compare_message_file"

  if [ -z "$baseline_times_csv" ]; then
    baseline_times_csv="$btime"
    optimized_times_csv="$otime"
  else
    baseline_times_csv="$baseline_times_csv,$btime"
    optimized_times_csv="$optimized_times_csv,$otime"
  fi

  if [ "$first_case" -eq 1 ]; then
    correct_cases_json="$correct_cases_json$case_json"
    first_case=0
  else
    correct_cases_json="$correct_cases_json,$case_json"
  fi

  if [ -n "$error_type" ]; then
    correct_cases_json="$correct_cases_json]"
    write_fail_result "correctness" "$error_type" "$case_message_file" "$correct_cases_json"
    rm -f "$case_message_file"
    exit 0
  fi
  rm -f "$case_message_file"
done < cases.tsv
correct_cases_json="$correct_cases_json]"

baseline_avg="$(printf '%s\n' "$baseline_times_csv" | mean_csv)"
optimized_avg="$(printf '%s\n' "$optimized_times_csv" | mean_csv)"
speedup="$(awk "BEGIN { if ($optimized_avg > 0) printf \"%.12f\", $baseline_avg / $optimized_avg; else printf \"0.000000\" }")"

cat > "$RESULT_PATH" <<EOF
{"pid":"$(json_escape_text "$PID")","status":"pass","stage":"performance","error_type":"","message":"","global_sf_n":$GLOBAL_SF_N,"baseline_time_ms":$baseline_avg,"optimized_time_ms":$optimized_avg,"speedup_ratio":$speedup,"baseline_times_ms":[$baseline_times_csv],"optimized_times_ms":[$optimized_times_csv],"cases":$correct_cases_json}
EOF

exit 0
