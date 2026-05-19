#!/bin/sh
set -u

RESULT_PATH="${1:-result.json}"

write_bootstrap_fail_result() {
  message="$1"
  printf '{"pid":"","status":"fail","stage":"exec","error_type":"bootstrap","message":"%s","global_sf_n":null,"baseline_time_ms":0.0,"optimized_time_ms":0.0,"speedup_ratio":0.0,"baseline_times_ms":[],"optimized_times_ms":[],"cases":[]}\n' "$message" > "$RESULT_PATH"
}

if [ ! -f "./runner_config.sh" ]; then
  write_bootstrap_fail_result "missing runner_config.sh"
  exit 0
fi

. ./runner_config.sh

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

  if cmp -s "$expected_norm" "$actual_norm"; then
    printf 'pass\n' > "$message_file"
    rm -f "$expected_norm" "$actual_norm"
    return 0
  fi

  expected_lines="$(awk 'END { print NR + 0 }' "$expected_norm")"
  actual_lines="$(awk 'END { print NR + 0 }' "$actual_norm")"
  if [ "$expected_lines" -eq 1 ] && [ "$actual_lines" -eq 1 ]; then
    expected_value="$(head -n 1 "$expected_norm")"
    actual_value="$(head -n 1 "$actual_norm")"
    if is_float_text "$expected_value" && is_float_text "$actual_value"; then
      awk -v a="$expected_value" -v b="$actual_value" -v tol="$FLOAT_TOLERANCE" 'BEGIN {
        diff = a - b;
        if (diff < 0) diff = -diff;
        if (diff <= tol) {
          print "pass";
          exit 0;
        }
        printf "float mismatch: abs diff %.12g > %.12g\n", diff, tol;
        exit 1;
      }' > "$message_file"
      rc="$?"
      rm -f "$expected_norm" "$actual_norm"
      return "$rc"
    fi
  fi

  printf 'output mismatch\n' > "$message_file"
  rm -f "$expected_norm" "$actual_norm"
  return 1
}

build_runtime_message() {
  err_file="$1"
  out_file="$2"
  message_file="$3"
  err_excerpt="$message_file.err"
  out_excerpt="$message_file.out"

  write_excerpt_file "$err_file" "$err_excerpt" 600
  write_excerpt_file "$out_file" "$out_excerpt" 600
  {
    if [ -s "$err_excerpt" ]; then
      printf 'stderr:\n'
      cat "$err_excerpt"
      if [ -s "$out_excerpt" ]; then
        printf '\n'
      fi
    fi
    if [ -s "$out_excerpt" ]; then
      printf 'stdout:\n'
      cat "$out_excerpt"
    fi
    if [ ! -s "$err_excerpt" ] && [ ! -s "$out_excerpt" ]; then
      printf 'process exited with non-zero status'
    fi
  } > "$message_file"
  rm -f "$err_excerpt" "$out_excerpt"
}

build_wrong_answer_message() {
  compare_file="$1"
  expected_file="$2"
  actual_file="$3"
  message_file="$4"
  expected_excerpt="$message_file.expected"
  actual_excerpt="$message_file.actual"

  write_excerpt_file "$expected_file" "$expected_excerpt" 400
  write_excerpt_file "$actual_file" "$actual_excerpt" 400
  {
    if [ -f "$compare_file" ]; then
      cat "$compare_file"
    else
      printf 'output mismatch'
    fi
    printf '\nexpected excerpt:\n'
    cat "$expected_excerpt"
    printf '\nactual excerpt:\n'
    cat "$actual_excerpt"
  } > "$message_file"
  rm -f "$expected_excerpt" "$actual_excerpt"
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
    sh -c "timeout '$COMPILE_TIMEOUT' $COMPILE_CMD '$src' -o '$bin' ${COMPILE_TAIL:-}" 2> "$err"
  else
    sh -c "$COMPILE_CMD '$src' -o '$bin' ${COMPILE_TAIL:-}" 2> "$err"
  fi
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

compile_one baseline.cpp ./baseline.bin baseline.compile.err
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
    run_with_timeout "$RUN_TIMEOUT" "$bin_path" < "$input_path" > "$prefix.out" 2> "$prefix.err"
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
    if compare_outputs \
      "correct.baseline.$testcase_index.out" \
      "correct.optimized.$testcase_index.out" \
      "$compare_message_file"
    then
      output_match=true
      : > "$case_message_file"
    else
      build_wrong_answer_message \
        "$compare_message_file" \
        "correct.baseline.$testcase_index.out" \
        "correct.optimized.$testcase_index.out" \
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
