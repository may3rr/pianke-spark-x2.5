#!/bin/sh
# 打包初赛提交物：dist/天天开心-片刻.zip
#
#   ./pack.sh                        用无声的演示视频
#   ./pack.sh ~/Music/bgm.mp3        把这段音乐配到演示视频上（循环补齐，结尾 3 秒淡出）
#   ./pack.sh ~/Movies/配好乐的.mp4   直接用已经配好音乐的视频
#
# zip 里：项目介绍 PPT（PDF）、演示视频、源代码（按 .gitignore 过滤，不含模型权重）、提交说明。
set -eu
cd "$(dirname "$0")"

TEAM="天天开心"
PRODUCT="片刻"
NAME="$TEAM-$PRODUCT"
DECK="presentation/out/片刻_初赛.pdf"
SILENT="presentation/out/片刻_演示视频.mp4"
SCORED="presentation/out/片刻_演示视频_配乐.mp4"
OUT="dist/$NAME.zip"

for f in "$DECK" "$SILENT"; do
  [ -f "$f" ] || { echo "缺少 ${f}" >&2; exit 1; }
done

# ---------------------------------------------------------------- 视频
VIDEO="$SILENT"
if [ $# -ge 1 ]; then
  SRC="$1"
  [ -f "$SRC" ] || { echo "找不到 ${SRC}" >&2; exit 1; }
  case "$(printf '%s' "$SRC" | tr '[:upper:]' '[:lower:]')" in
    *.mp4|*.mov|*.m4v)
      VIDEO="$SRC"
      ;;
    *.mp3|*.m4a|*.aac|*.wav|*.flac|*.ogg)
      DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$SILENT")
      FADE=$(echo "$DUR - 3" | bc)
      echo "配乐：${SRC} → ${SCORED}（${DUR} 秒）"
      ffmpeg -v error -y -i "$SILENT" -stream_loop -1 -i "$SRC" \
        -map 0:v -map 1:a -c:v copy -c:a aac -b:a 192k \
        -af "afade=t=in:d=1,afade=t=out:st=$FADE:d=3" -t "$DUR" \
        -movflags +faststart "$SCORED"
      VIDEO="$SCORED"
      ;;
    *)
      echo "不认识的文件类型：${SRC}（音乐用 mp3/m4a/wav，视频用 mp4/mov）" >&2
      exit 1
      ;;
  esac
else
  echo "提示：没有给音乐，打包的是无声版视频。"
fi

# ---------------------------------------------------------------- 整理目录
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
ROOT="$STAGE/$NAME"
mkdir -p "$ROOT/3_源代码"

cp "$DECK" "$ROOT/1_项目介绍PPT_$PRODUCT.pdf"
cp "$VIDEO" "$ROOT/2_演示视频_$PRODUCT.mp4"

# 源代码：git 跟踪的和未被忽略的文件；成品与赛题原文不重复放
git -c core.quotepath=off ls-files --cached --others --exclude-standard \
  | grep -v -e '^presentation/out/' -e '^Problem\.md$' -e '^dist/' \
  > "$STAGE/files.txt"
rsync -a --files-from="$STAGE/files.txt" ./ "$ROOT/3_源代码/"

cat > "$ROOT/提交说明.txt" <<EOF
$NAME  初赛提交材料
Spark-X2.5 端侧模型创新挑战赛

1_项目介绍PPT_$PRODUCT.pdf
    团队介绍、项目背景、产品功能、技术实现、原创性声明。

2_演示视频_$PRODUCT.mp4
    真机录屏：Apple M3 Pro / 18GB 上运行 Spark-X2.5-4B 与 1.7B（llama.cpp，Q4_K_M）。
    画面由应用的界面驱动脚本自动操作并逐帧录下，没有剪辑模型输出；
    模型思考较久的片段加速播放，画面左下角标出倍速和实际用时。

3_源代码/
    macOS 桌面应用（Electron + Python 后端）。运行方法见 README.md。
    模型权重约 3.7 GB，未放入压缩包，按 README 第 1 步下载。
EOF

# ---------------------------------------------------------------- 压缩
# Python 的 zipfile 会给中文文件名打 UTF-8 标记，Windows 解压不乱码
mkdir -p dist
rm -f "$OUT"
python3 - "$STAGE" "$NAME" "$OUT" <<'PY'
import os, sys, zipfile
stage, name, out = sys.argv[1:]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for d, _, files in os.walk(os.path.join(stage, name)):
        for f in sorted(files):
            if f == ".DS_Store":
                continue
            p = os.path.join(d, f)
            arc = os.path.relpath(p, stage)
            # 视频和 PDF 已经压缩过，直接存
            kind = zipfile.ZIP_STORED if f.endswith((".mp4", ".pdf", ".png", ".jpg")) else zipfile.ZIP_DEFLATED
            z.write(p, arc, compress_type=kind)
PY

SIZE=$(du -m "$OUT" | cut -f1)
echo "完成：${OUT}（${SIZE} MB）"
if [ "$SIZE" -ge 1024 ]; then
  echo "超过 1 GB：按赛题要求，需要把视频放网盘，在材料里附永久链接。" >&2
fi
python3 - "$OUT" <<'PY'
import sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
src = [i for i in z.infolist() if "/3_源代码/" in i.filename]
for i in z.infolist():
    if i not in src:
        print(f"  {i.file_size / 1e6:8.1f} MB  {i.filename}")
print(f"  {sum(i.file_size for i in src) / 1e6:8.1f} MB  3_源代码/（{len(src)} 个文件）")
PY
