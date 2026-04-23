#!/usr/bin/env bash
# poll_kernel_and_continue.sh — Hermes skill mlops/kaggle/kaggle-experiment 附带的模板脚本
#
# 【脚本做什么】
# 1) 用 kaggle CLI 周期性查询指定 Kernel 的运行状态；
# 2) 若状态显示失败/取消，则记录并退出码 1；
# 3) 若成功完成，则（可选）下载 Kernel 输出到本次 run 目录，再（可选）用 Hermes 执行下一轮 `hermes chat -q`；
# 4) 若轮询次数用尽仍未结束，则记为超时并退出码 2。
#
# 使用方式（复制到实验仓库，建议路径 scripts/kaggle/，chmod +x，填好变量后后台跑）：
#
#   cd /path/to/experiment-repo
#   nohup env KAGGLE_KERNEL_REF="owner/kernel-slug" \
#     HERMES_NEXT_PROMPT_FILE="scripts/kaggle/next_turn_prompt.txt" \
#     bash scripts/kaggle/poll_kernel_and_continue.sh \
#     >> experiments/runs/poller_nohup.log 2>&1 &
#
# 依赖：已登录的 kaggle CLI；若要用 Hermes 续跑，需 hermes 在 PATH 上。
#
# 环境变量（必填）：
#   KAGGLE_KERNEL_REF     所有者/短名，例如 "janedoe/my-notebook"
#
# 环境变量（可选）：
#   REPO_ROOT             仓库根目录（默认：脚本启动时的当前目录）
#   POLL_INTERVAL_SEC     两次查询之间的休眠秒数（默认 600）
#   MAX_POLLS             最大轮询次数（默认 144，配合 600s 约 24 小时）
#   RUN_ID                experiments/runs/ 下子目录名（默认 UTC 时间戳）
#   HERMES_BIN            Hermes 可执行文件（默认 hermes）
#   HERMES_NEXT_PROMPT    单行提示，传给：hermes chat -q "..."
#   HERMES_NEXT_PROMPT_FILE  从文件读入多行内容作为 -q 参数（多行时优先用这个）
#   SKIP_KAGGLE_OUTPUT    设为 1 则成功后不执行 kaggle kernels output
#   SKIP_HERMES           设为 1 则成功后不调用 Hermes

# -u：未定义变量报错；-o pipefail：管道中任一命令失败则整体失败
set -uo pipefail

# 必须指定要监控的 Kernel（owner/slug）
KERNEL="${KAGGLE_KERNEL_REF:-}"
if [[ -z "$KERNEL" ]]; then
  echo "error: set KAGGLE_KERNEL_REF=owner/kernel-slug" >&2
  exit 1
fi

# 进入仓库根，后续路径与 Hermes 调用都以此为基准
REPO_ROOT="${REPO_ROOT:-$(pwd)}"
cd "$REPO_ROOT" || {
  echo "error: cannot cd to REPO_ROOT=$REPO_ROOT" >&2
  exit 1
}

# 轮询与本次运行目录相关默认值
POLL_INTERVAL_SEC="${POLL_INTERVAL_SEC:-600}"
MAX_POLLS="${MAX_POLLS:-144}"
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
RUN_DIR="${RUN_DIR:-$REPO_ROOT/experiments/runs/$RUN_ID}"
HERMES_BIN="${HERMES_BIN:-hermes}"

mkdir -p "$RUN_DIR"
# 此后标准输出/错误都追加写入本次 run 的 poller.log（便于 nohup 外再留一份结构化日志）
exec >>"$RUN_DIR/poller.log" 2>&1
echo "=== poll_kernel_and_continue start $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
echo "kernel=$KERNEL repo=$REPO_ROOT interval=${POLL_INTERVAL_SEC}s max_polls=$MAX_POLLS"

poll=0
status_raw=""
# 主循环：反复查状态，直到成功、明确失败、或超时
while ((poll < MAX_POLLS)); do
  poll=$((poll + 1))
  echo "--- poll #$poll $(date -u +%Y-%m-%dT%H:%M:%SZ) ---"
  # 查询状态失败（网络/鉴权等）时不退出，只告警后休眠重试
  set +e
  status_raw="$(kaggle kernels status "$KERNEL" 2>&1)"
  kaggle_rc=$?
  echo "$status_raw"
  {
    echo "poll=$poll utc=$(date -u +%Y-%m-%dT%H:%M:%SZ) rc=$kaggle_rc"
    echo "$status_raw"
  } >>"$RUN_DIR/status_history.log"

  if ((kaggle_rc != 0)); then
    echo "warning: kaggle kernels status returned $kaggle_rc (auth/network?); sleeping and retrying"
    sleep "$POLL_INTERVAL_SEC"
    continue
  fi

  # 统一转小写后用关键词判断终态（依赖 kaggle status 文案中的英文词）
  lc=$(echo "$status_raw" | tr '[:upper:]' '[:lower:]')
  if echo "$lc" | grep -qE '\b(error|failed|failure|cancelled|canceled)\b'; then
    echo "detected terminal failure from status text"
    printf '%s\n' "$status_raw" >"$RUN_DIR/status_final.txt"
    printf 'kernel_ref=%s\nrun_id=%s\noutcome=failed\npolls=%s\n' "$KERNEL" "$RUN_ID" "$poll" >"$RUN_DIR/summary.txt"
    exit 1
  fi

  if echo "$lc" | grep -qE '\b(complete|completed|success)\b'; then
    echo "detected successful completion from status text"
    printf '%s\n' "$status_raw" >"$RUN_DIR/status_final.txt"
    printf 'kernel_ref=%s\nrun_id=%s\noutcome=success\npolls=%s\n' "$KERNEL" "$RUN_ID" "$poll" >"$RUN_DIR/summary.txt"
    break
  fi

  echo "kernel not in terminal state yet; sleeping ${POLL_INTERVAL_SEC}s"
  sleep "$POLL_INTERVAL_SEC"
done

# 循环结束但若从未写入终态文件，说明是次数用尽而非成功 break
if ((poll >= MAX_POLLS)) && [[ ! -f "$RUN_DIR/status_final.txt" ]]; then
  echo "timeout: exceeded MAX_POLLS=$MAX_POLLS"
  printf 'kernel_ref=%s\nrun_id=%s\noutcome=timeout\npolls=%s\n' "$KERNEL" "$RUN_ID" "$poll" >"$RUN_DIR/summary.txt"
  exit 2
fi

# 成功路径：按需拉取 Kernel 输出到 RUN_DIR/output
if [[ "${SKIP_KAGGLE_OUTPUT:-0}" != "1" ]]; then
  mkdir -p "$RUN_DIR/output"
  set +e
  kaggle kernels output "$KERNEL" -p "$RUN_DIR/output" -o 2>&1 | tee "$RUN_DIR/kaggle_output.log"
  set +e
fi

# 用户可跳过 Hermes，仅完成轮询与下载
if [[ "${SKIP_HERMES:-0}" == "1" ]]; then
  echo "SKIP_HERMES=1 — not invoking Hermes"
  exit 0
fi

# 组装下一轮对话的 prompt：文件优先，否则单行环境变量
prompt=""
if [[ -n "${HERMES_NEXT_PROMPT_FILE:-}" ]]; then
  if [[ ! -f "$HERMES_NEXT_PROMPT_FILE" ]]; then
    echo "error: HERMES_NEXT_PROMPT_FILE not found: $HERMES_NEXT_PROMPT_FILE" >&2
    exit 1
  fi
  prompt=$(cat "$HERMES_NEXT_PROMPT_FILE")
elif [[ -n "${HERMES_NEXT_PROMPT:-}" ]]; then
  prompt="$HERMES_NEXT_PROMPT"
else
  echo "warning: set HERMES_NEXT_PROMPT or HERMES_NEXT_PROMPT_FILE to run Hermes; exiting after fetch"
  exit 0
fi

# 在仓库根执行 Hermes，并把日志写入本次 run
echo "=== invoking Hermes $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
cd "$REPO_ROOT" || exit 1
set +e
"$HERMES_BIN" chat -q "$prompt" 2>&1 | tee "$RUN_DIR/hermes_invocation.log"
hermes_rc="${PIPESTATUS[0]}"
set +e
echo "hermes chat -q finished with rc=$hermes_rc"
exit "$hermes_rc"
