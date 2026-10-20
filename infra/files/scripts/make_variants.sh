#!/bin/sh
# A/B-варианты одного ролика: РАЗНЫЙ ХУК (текст в начале), опционально разная длина/старт.
# Это не маскировка дублей: каждый вариант реально отличается и предназначен для теста хуков.
#
# Использование:
#   make_variants.sh INPUT.mp4 OUTDIR HOOKS.txt [TRIM_START_SEC] [MAX_LEN_SEC]
#
# HOOKS.txt - по одному хуку в строке (каждая строка = один вариант).
# Переменные окружения:
#   FONT       путь к .ttf (по умолчанию ищется DejaVuSans / Arial)
#   AI_LABEL   текст метки внизу кадра (по умолчанию пусто = без надписи)
#   HOOK_SECS  сколько секунд показывать хук (по умолчанию 2.5)
# Результат: OUTDIR/<имя>_vN.mp4 и OUTDIR/variants.csv (лог параметров для таблицы).
set -eu

IN="${1:?нужен входной файл}"; OUT="${2:?нужна папка вывода}"; HOOKS="${3:?нужен файл с хуками}"
TRIM="${4:-0}"; MAXLEN="${5:-0}"
AI_LABEL="${AI_LABEL-}"; HOOK_SECS="${HOOK_SECS:-2.5}"

if [ -z "${FONT:-}" ]; then
  for f in /usr/share/fonts/dejavu/DejaVuSans.ttf /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf \
           /files/fonts/font.ttf C:/Windows/Fonts/arial.ttf /c/Windows/Fonts/arial.ttf; do
    [ -f "$f" ] && FONT="$f" && break
  done
fi
[ -n "${FONT:-}" ] && [ -f "$FONT" ] || { echo "Не найден шрифт, задайте FONT=путь.ttf" >&2; exit 1; }

mkdir -p "$OUT"
# Пути в фильтрах ffmpeg (особенно "C:" на Windows) капризны, поэтому ffmpeg запускаем
# внутри временной папки, куда копируем шрифт, и ссылаемся на файлы по коротким именам.
# HOOKS="-" означает "без текста на видео": рендерится один вариант только с масштабированием.
NOHOOK=0
NOHOOK_FILE=""
if [ "$HOOKS" = "-" ]; then NOHOOK=1; NOHOOK_FILE=$(mktemp); HOOKS="$NOHOOK_FILE"; printf 'x\n' > "$HOOKS"; fi
IN=$(cd "$(dirname "$IN")" && pwd)/$(basename "$IN"); OUT=$(cd "$OUT" && pwd)
HOOKS=$(cd "$(dirname "$HOOKS")" && pwd)/$(basename "$HOOKS")
BASE=$(basename "$IN"); BASE="${BASE%.*}"
LOG="$OUT/variants.csv"
echo "variant,file,hook,trim_start,max_len,hook_secs,ai_label,duration_sec" > "$LOG"

TMP=$(mktemp -d); trap 'rm -rf "$TMP"; [ -z "$NOHOOK_FILE" ] || rm -f "$NOHOOK_FILE"' EXIT
cp "$FONT" "$TMP/font.ttf"
N=0
while IFS= read -r HOOK || [ -n "$HOOK" ]; do
  HOOK=$(printf '%s' "$HOOK" | tr -d '\r')
  [ -z "$HOOK" ] && continue
  N=$((N+1))
  # Длинный хук обрезается до 90 знаков и переносится по словам (~22 знака в строке), чтобы не выходить за края кадра.
  HOOK=$(printf '%s' "$HOOK" | cut -c1-90)
  printf '%s' "$HOOK" | fold -s -w 22 | sed 's/[[:space:]]*$//' > "$TMP/hook$N.txt"       # текст через файл: без проблем с кавычками
  printf '%s' "$AI_LABEL" > "$TMP/label.txt"

  VF="scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1"
  [ "$NOHOOK" = 1 ] || VF="$VF,drawtext=fontfile=font.ttf:textfile=hook$N.txt:fontsize=64:fontcolor=white:borderw=4:bordercolor=black:line_spacing=10:text_align=center:x=(w-text_w)/2:y=h*0.15:enable='lt(t,$HOOK_SECS)'"
  [ -n "$AI_LABEL" ] && VF="$VF,drawtext=fontfile=font.ttf:textfile=label.txt:fontsize=32:fontcolor=white@0.85:borderw=2:bordercolor=black:x=(w-text_w)/2:y=h-140"

  ARGS="-ss $TRIM"
  [ "$MAXLEN" != "0" ] && ARGS="$ARGS -t $MAXLEN"
  FILE="${BASE}_v$N.mp4"
  # shellcheck disable=SC2086
  (cd "$TMP" && ffmpeg -y -loglevel error $ARGS -i "$IN" -vf "$VF" \
    -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -c:a aac -b:a 128k -movflags +faststart "$OUT/$FILE")

  DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT/$FILE")
  SAFE=$(printf '%s' "$HOOK" | sed 's/"/""/g')
  echo "v$N,$FILE,\"$SAFE\",$TRIM,$MAXLEN,$HOOK_SECS,\"$AI_LABEL\",$DUR" >> "$LOG"
  echo "OK v$N: $FILE"
done < "$HOOKS"
[ "$N" -gt 0 ] || { echo "В файле хуков нет строк" >&2; exit 1; }
