# n8n + ffmpeg. В официальном образе n8n нет пакетного менеджера,
# поэтому берём готовый статический ffmpeg из отдельного образа.
ARG N8N_VERSION
FROM mwader/static-ffmpeg:7.1 AS ffmpeg

FROM n8nio/n8n:${N8N_VERSION}
COPY --from=ffmpeg /ffmpeg /usr/local/bin/ffmpeg
COPY --from=ffmpeg /ffprobe /usr/local/bin/ffprobe
