#!/bin/sh
set -eu

SITE_ID="${SITE_ID:-condo-01}"
CAMERA_IDS="${CAMERA_IDS:-cam-01,cam-02}"
MEDIAMTX_RTSP_BASE="${MEDIAMTX_RTSP_BASE:-rtsp://mediamtx:8554}"

# Para una camara real ya no necesitas este contenedor.
# El camino esperado es:
# 1. quitar stream-publisher-<site> del docker-compose
# 2. cambiar el path correspondiente en infra/mediamtx/<site>.yml a source: rtsp://usuario:password@IP/stream
# 3. mantener o reemplazar camera-sim por un collector edge que reporte heartbeat, snapshots y metadata reales

csv_to_lines() {
  printf "%s" "$1" | tr "," "\n"
}

pattern_for_index() {
  case "$1" in
    0) printf "testsrc2=size=1280x720:rate=25" ;;
    1) printf "smptebars=size=1280x720:rate=25" ;;
    2) printf "testsrc=size=1280x720:rate=25" ;;
    *) printf "testsrc2=size=1280x720:rate=25" ;;
  esac
}

publish_stream() {
  camera_id="$1"
  index="$2"
  freq=$((440 + (index * 110)))
  pattern="$(pattern_for_index "$index")"
  target="${MEDIAMTX_RTSP_BASE}/${SITE_ID}/${camera_id}"

  while true; do
    echo "publicando stream simulado hacia ${target}"
    ffmpeg \
      -hide_banner \
      -loglevel warning \
      -re \
      -f lavfi -i "${pattern}" \
      -f lavfi -i "sine=frequency=${freq}:sample_rate=48000" \
      -c:v libx264 \
      -pix_fmt yuv420p \
      -preset veryfast \
      -tune zerolatency \
      -profile:v baseline \
      -level 3.1 \
      -g 50 \
      -keyint_min 50 \
      -c:a aac \
      -b:a 128k \
      -ar 48000 \
      -ac 2 \
      -f rtsp \
      -rtsp_transport tcp \
      "${target}"
    echo "ffmpeg termino para ${camera_id}; reintentando en 2 segundos"
    sleep 2
  done
}

index=0
for camera_id in $(csv_to_lines "$CAMERA_IDS"); do
  publish_stream "$camera_id" "$index" &
  index=$((index + 1))
done

wait
