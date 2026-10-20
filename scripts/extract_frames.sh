#!/bin/sh
# Извлекает 3 кадра (на 25%, 50% и 75% длительности) в уменьшенном виде - для описания видео ИИ.
# Использование: extract_frames.sh INPUT.mp4 OUTDIR
set -eu
IN="${1:?нужен входной файл}"; OUT="${2:?нужна папка вывода}"
mkdir -p "$OUT"
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$IN" | head -n1)
DUR=${DUR%.*}; [ -n "$DUR" ] || DUR=4
for i in 1 2 3; do
  T=$(( DUR * i / 4 ))
  ffmpeg -y -loglevel error -ss "$T" -i "$IN" -frames:v 1 -vf "scale=512:-2" -q:v 5 "$OUT/f$i.jpg"
done
echo "OK frames: $OUT"
