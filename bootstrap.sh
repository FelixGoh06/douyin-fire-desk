#!/usr/bin/env bash
# One-command bootstrap for common Linux servers.
set -euo pipefail

REPO_NAME="douyin-fire-desk"
GITEE_URL="https://gitee.com/gongyu2006/douyin-fire-desk.git"
GITHUB_URL="https://github.com/FelixGoh06/douyin-fire-desk.git"
SOURCE="auto"

usage() {
  cat <<'EOF'
用法：bash bootstrap.sh [--gitee|--github]

默认优先使用 Gitee，失败后使用 GitHub，然后打开 GONGYU 菜单。
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --gitee) SOURCE="gitee"; shift ;;
    --github) SOURCE="github"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf '未知选项：%s\n' "$1" >&2; usage >&2; exit 1 ;;
  esac
done

[[ -f /etc/os-release ]] || { printf '无法识别 Linux 发行版。\n' >&2; exit 1; }

[[ "$EUID" -eq 0 ]] || { printf '请以 root 运行启动脚本：curl ... | sudo bash\n' >&2; exit 1; }
[[ -d /run/systemd/system ]] && command -v systemctl >/dev/null 2>&1 || {
  printf 'Web 管理平台需要 systemd。请在服务器主机的 SSH 终端运行，不要在 Docker 容器终端中运行。\n' >&2
  exit 1
}

target="/root/${REPO_NAME}"

open_menu() {
  cd "$target"
  # `curl ... | sudo bash` gives this bootstrap script a pipe as stdin. Reconnect
  # the interactive GONGYU menu to the caller's terminal before opening it.
  # Some cloud terminal implementations expose /dev/tty without reporting it as
  # readable to `[[ -r ]]`, so test opening it rather than inspecting permissions.
  if { true </dev/tty; } 2>/dev/null; then
    exec bash gongyu.sh </dev/tty
  fi
  printf '\nGONGYU 已准备就绪，但当前终端不支持交互输入。\n'
  printf '请手动打开菜单：\n  cd %s && bash gongyu.sh\n' "$target"
}

if [[ -e "$target" ]]; then
  if [[ ! -d "$target" || ! -f "$target/gongyu.sh" ]]; then
    printf '目录已存在但不是有效项目目录：%s\n请更换目录名或处理该目录后重试。\n' "$target" >&2
    exit 1
  fi
  printf '检测到已有项目目录：%s\n不重复下载，正在打开 GONGYU 脚本主菜单。\n' "$target"
  open_menu
  exit 0
fi

if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y ca-certificates curl git
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y ca-certificates curl git
elif command -v yum >/dev/null 2>&1; then
  yum install -y ca-certificates curl git
else
  printf '暂不支持当前系统的包管理器。已支持 apt、dnf 和 yum 系统。\n' >&2
  exit 1
fi

clone() {
  local url="$1"
  git clone --depth 1 "$url" "$target"
}

case "$SOURCE" in
  gitee) clone "$GITEE_URL" ;;
  github) clone "$GITHUB_URL" ;;
  auto) clone "$GITEE_URL" || { rm -rf "$target"; clone "$GITHUB_URL"; } ;;
esac

open_menu
