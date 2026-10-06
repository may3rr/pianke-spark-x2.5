#!/bin/sh
# 一键启动片刻（开发模式）：构建界面并打开应用。后端和两个模型由应用自动拉起。
cd "$(dirname "$0")/app" || exit 1
export PIANKE_PYTHON="${PIANKE_PYTHON:-/opt/anaconda3/envs/claude/bin/python}"
[ -d node_modules ] || npm install
npx electron-vite build >/dev/null && exec npx electron .
