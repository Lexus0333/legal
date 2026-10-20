#!/bin/sh
# Накладывает музыку из локальной библиотеки на видео (на месте: файл заменяется).
# Использование: add_music.sh VIDEO MUSIC_DIR [MODE] [VOLUME]
#   MODE:  off    - ничего не делать
#          silent - добавлять музыку только если у видео нет звука (по умолчанию)
#          mix    - добавлять и к видео со звуком (музыка тише оригинала)
#   VOLUME: громкость музыки после выравнивания (по умолчанию 1.0)
# Библиотека: MUSIC_DIR/<настроение>/*.mp3|m4a|wav|ogg|aac|flac (настроения: calm, energetic, mysterious и любые другие);
# файлы прямо в MUSIC_DIR считаются подходящими для любого видео.
# Последняя строка вывода: "MUSIC <настроение>|<трек>" или "MUSIC none|<причина>".
set -eu
VID="${1:?нужен файл видео}"; MDIR="${2:?нужна папка с музыкой}"; MODE="${3:-silent}"; VOL="${4:-1}"
SELF_DIR=$(cd "$(dirname "$0")" && pwd)
AUD='\.(mp3|m4a|wav|ogg|aac|flac)$'

[ "$MODE" = off ] && { echo "MUSIC none|off"; exit 0; }
# "Есть звук" = есть аудиодорожка И она не беззвучная (средняя громкость выше порога, по умолчанию -45 дБ).
HAS_AUDIO=$(ffprobe -v error -select_streams a -show_entries stream=index -of csv=p=0 "$VID" | head -n1 || true)
if [ -n "$HAS_AUDIO" ]; then
  MEAN=$(ffmpeg -nostdin -nostats -i "$VID" -vn -af volumedetect -f null - 2>&1 | grep -o 'mean_volume: [-0-9.]*' | cut -d' ' -f2 | head -n1 || true)
  if [ -z "$MEAN" ] || awk -v m="$MEAN" -v t="${MUSIC_SILENCE_DB:--45}" 'BEGIN{exit !(m<=t)}'; then HAS_AUDIO=""; fi
fi
if [ -n "$HAS_AUDIO" ] && [ "$MODE" = silent ]; then echo "MUSIC none|video already has sound"; exit 0; fi
[ -d "$MDIR" ] || { echo "MUSIC none|no music folder"; exit 0; }

# список треков в папке (по одному в строке)
tracks() { find "$1" -maxdepth 1 -type f 2>/dev/null | grep -i -E "$AUD" || true; }
pick() { awk -v seed="$(date +%s)$$" 'BEGIN{srand(seed)} {a[NR]=$0} END{if (NR) print a[int(rand()*NR)+1]}'; }

# настроение ролика и подбор трека: нужное настроение -> любое другое настроение -> файлы в корне
MOOD=$(sh "$SELF_DIR/analyze_mood.sh" "$VID" 2>/dev/null | cut -d' ' -f1 || true)
[ -n "$MOOD" ] || MOOD=calm
TRACK=$(tracks "$MDIR/$MOOD" | pick)
if [ -z "$TRACK" ]; then
  ALL=$( { for d in "$MDIR"/*/; do [ -d "$d" ] && tracks "${d%/}"; done; tracks "$MDIR"; } )
  TRACK=$(printf '%s\n' "$ALL" | grep -v '^$' | pick || true)
  [ -n "$TRACK" ] && MOOD="other"
fi
[ -n "${TRACK:-}" ] || { echo "MUSIC none|no tracks in $MDIR"; exit 0; }

D=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$VID" | head -n1)
FS=$(awk -v d="$D" 'BEGIN{ s=d-1.5; if (s<0) s=0; printf "%.2f", s }')
TMP="$VID.music.mp4"
# трек: выравниваем громкость, зацикливаем, обрезаем под ролик, плавно включаем и выключаем
MFX="loudnorm=I=-16:TP=-1.5:LRA=11,volume=$VOL,afade=t=in:d=0.5,afade=t=out:st=$FS:d=1.5"
if [ -n "$HAS_AUDIO" ]; then
  FC="[1:a]$MFX,volume=0.5[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"
else
  FC="[1:a]$MFX[a]"
fi
ffmpeg -nostdin -y -loglevel error -i "$VID" -stream_loop -1 -i "$TRACK" -filter_complex "$FC" -map 0:v -map "[a]" \
  -c:v copy -c:a aac -b:a 160k -t "$D" -movflags +faststart "$TMP"
mv "$TMP" "$VID"
echo "MUSIC $MOOD|$(basename "$TRACK")"
