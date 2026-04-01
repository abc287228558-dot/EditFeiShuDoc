#!/bin/zsh

set -euo pipefail

SCRIPT_DIR=${0:A:h}
DEFAULT_DINGDONG="$SCRIPT_DIR/叮咚.mp3"
DEFAULT_VOICE="Tingting"
DEFAULT_PREFIX="来亮啦"
DEFAULT_SUFFIX="个新数据"
DEFAULT_RATE=210
TEMP_DINGDONG=""

cleanup() {
  if [[ -n "$TEMP_DINGDONG" && -f "$TEMP_DINGDONG" ]]; then
    rm -f "$TEMP_DINGDONG"
  fi
}

trap cleanup EXIT

usage() {
  cat <<EOF
用法:
  ./announce_new_data.sh <数量> [--voice 音色] [--dingdong 文件路径]

示例:
  ./announce_new_data.sh 5
  ./announce_new_data.sh 12 --voice "Tingting"

说明:
  1. 先播放叮咚音频
  2. 再用 macOS 系统朗读“来亮啦，有X个新数据”
EOF
}

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

count=""
voice="$DEFAULT_VOICE"
dingdong="$DEFAULT_DINGDONG"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --voice)
      voice="${2:-}"
      shift 2
      ;;
    --dingdong)
      dingdong="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      if [[ -z "$count" ]]; then
        count="$1"
        shift
      else
        echo "不支持的参数: $1" >&2
        usage
        exit 1
      fi
      ;;
  esac
done

if [[ -z "$count" ]]; then
  echo "请提供新数据数量。" >&2
  usage
  exit 1
fi

if ! [[ "$count" =~ '^[0-9]+$' ]]; then
  echo "数量必须是非负整数，当前收到: $count" >&2
  exit 1
fi

if [[ ! -f "$dingdong" ]]; then
  echo "未找到叮咚音频: $dingdong" >&2
  exit 1
fi

if ! command -v afplay >/dev/null 2>&1; then
  echo "系统缺少 afplay，无法播放叮咚音频。" >&2
  exit 1
fi

if ! command -v say >/dev/null 2>&1; then
  echo "系统缺少 say，无法执行朗读。" >&2
  exit 1
fi

play_dingdong() {
  local input_file="$1"
  local play_file="$input_file"

  if [[ "${input_file:e:l}" == "mp3" ]] && command -v ffmpeg >/dev/null 2>&1; then
    TEMP_DINGDONG="$(mktemp /tmp/dingdong.XXXXXX.wav)"
    ffmpeg -loglevel error -y -i "$input_file" -c:a pcm_s16le "$TEMP_DINGDONG"
    play_file="$TEMP_DINGDONG"
  fi

  afplay "$play_file"
}

speech_text="${DEFAULT_PREFIX}，有${count}${DEFAULT_SUFFIX}"

play_dingdong "$dingdong"
say -v "$voice" "[[rate ${DEFAULT_RATE}]]${speech_text}"
