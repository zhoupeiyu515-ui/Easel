#!/usr/bin/env bash
# sync-upstream.sh — 一键把上游（ZJU-REAL/Easel）的最新改动同步到本地分支。
#
# 这是 **fork 本地工具**，不属于上游功能：给上游提 PR 时请勿带上本文件与 DEVELOPMENT.md。
#
# 用法（在仓库根跑）：
#   ./sync-upstream.sh                  # 拉上游 + 把当前分支 rebase 到 upstream/main
#   ./sync-upstream.sh --merge          # 同上，但用 merge 而不是 rebase
#   ./sync-upstream.sh --check          # 只看上游有没有新提交，不改动任何东西
#   ./sync-upstream.sh --onto main      # 指定要同步的本地分支（默认当前分支）
#
# 网络：国内直连 github.com 常被重置。脚本在直连失败时自动切到镜像
# （可用 EASEL_GIT_MIRROR 覆盖，默认 https://ghproxy.net/ ）。
set -euo pipefail

UPSTREAM_REMOTE="${UPSTREAM_REMOTE:-upstream}"
UPSTREAM_BRANCH="${UPSTREAM_BRANCH:-main}"
MIRROR="${EASEL_GIT_MIRROR:-https://ghproxy.net/}"
UPSTREAM_URL_DEFAULT="https://github.com/ZJU-REAL/Easel.git"

MODE="rebase"
TARGET_BRANCH=""
CHECK_ONLY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --merge) MODE="merge"; shift ;;
    --check) CHECK_ONLY=1; shift ;;
    --onto) TARGET_BRANCH="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "未知参数：$1（--help 看用法）" >&2; exit 2 ;;
  esac
done

cd "$(git rev-parse --show-toplevel)"

if ! git remote get-url "$UPSTREAM_REMOTE" >/dev/null 2>&1; then
  echo "→ 未配置 $UPSTREAM_REMOTE 远程，自动添加"
  git remote add "$UPSTREAM_REMOTE" "$UPSTREAM_URL_DEFAULT"
fi

# ---- 拉取上游：先直连，失败则走镜像 ----
# 用显式 refspec（而不是 `git fetch <remote> <branch>`）——后者只写 FETCH_HEAD，
# 不会更新 upstream/main，后面的 diff / rebase 就没有可用的引用。
fetch_upstream() {
  local url refspec
  url="$(git remote get-url "$UPSTREAM_REMOTE")"
  refspec="+refs/heads/${UPSTREAM_BRANCH}:refs/remotes/${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH}"
  echo "→ 拉取 $UPSTREAM_REMOTE（$url）"
  if git fetch "$UPSTREAM_REMOTE" "$refspec" --tags 2>/dev/null; then
    return 0
  fi
  echo "⚠️  直连失败，改用镜像 ${MIRROR}" >&2
  git fetch "${MIRROR}${url}" "$refspec" --tags
}

fetch_upstream

if ! git rev-parse --verify --quiet "${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH}" >/dev/null; then
  echo "❌ 拿不到 ${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH}，检查网络或 EASEL_GIT_MIRROR" >&2
  exit 1
fi
NEW="$(git rev-list --count "HEAD..${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH}")"
echo "→ 上游新增提交：${NEW} 个"
if [ "$NEW" = "0" ]; then
  echo "✅ 已是最新，无需同步"
  exit 0
fi
if [ "$CHECK_ONLY" = "1" ]; then
  echo "（--check 模式，未改动本地分支）"
  git --no-pager log --oneline "HEAD..${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH}" | head -20
  exit 0
fi

# ---- 干净检查 ----
BRANCH="${TARGET_BRANCH:-$(git rev-parse --abbrev-ref HEAD)}"
if [ -n "$(git status --porcelain)" ]; then
  echo "❌ 工作区有未提交改动，先 commit 或 stash 再同步：" >&2
  git status --short >&2
  exit 1
fi
if [ "$TARGET_BRANCH" != "" ]; then
  git checkout "$BRANCH"
fi

# ---- 同步 ----
if [ "$MODE" = "merge" ]; then
  echo "→ git merge ${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH} （分支：$BRANCH）"
  git merge "${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH}"
else
  echo "→ git rebase ${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH} （分支：$BRANCH）"
  if ! git rebase "${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH}"; then
    cat >&2 <<'EOF'

⚠️  rebase 遇到冲突。处理步骤：
  1. git status                查看冲突文件（both modified）
  2. 手动改完冲突，git add <文件>
  3. git rebase --continue
  中途想放弃回退：git rebase --abort
EOF
    exit 1
  fi
fi

echo "✅ 同步完成：$BRANCH 已跟上 ${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH}"
echo "   推送到你自己的 fork： git push --force-with-lease origin $BRANCH"
