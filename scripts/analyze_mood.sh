#!/bin/sh
# Оценивает настроение ролика без ИИ: средняя яркость и количество движения в кадре.
# Использование: analyze_mood.sh INPUT.mp4
# Печатает одну строку: "<mood> luma=<яркость 0-255> motion=<движение 0-255>"
# Правила (пороги можно менять переменными окружения):
#   движение >= MOOD_MOTION_HIGH            -> energetic
#   яркость  <  MOOD_LUMA_DARK              -> mysterious
#   иначе                                   -> calm
set -eu
IN="${1:?нужен входной файл}"
HIGH="${MOOD_MOTION_HIGH:-10}"
DARK="${MOOD_LUMA_DARK:-105}"

avg() { grep -o "YAVG=[0-9.]*" | cut -d= -f2 | awk '{s+=$1;n++} END{printf "%.2f", n?s/n:0}'; }

LUMA=$(ffmpeg -nostdin -v error -i "$IN" -an -vf "fps=2,scale=160:-2,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-" -f null - 2>/dev/null | avg)
MOTION=$(ffmpeg -nostdin -v error -i "$IN" -an -vf "fps=4,scale=160:-2,tblend=all_mode=difference,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-" -f null - 2>/dev/null | avg)

MOOD=$(awk -v l="$LUMA" -v m="$MOTION" -v h="$HIGH" -v d="$DARK" 'BEGIN{ if (m>=h) print "energetic"; else if (l<d) print "mysterious"; else print "calm" }')
# если анализ не удался (нулевые значения), не гадаем: спокойное настроение по умолчанию
if [ "$LUMA" = "0.00" ] && [ "$MOTION" = "0.00" ]; then MOOD=calm; fi
echo "$MOOD luma=$LUMA motion=$MOTION"
