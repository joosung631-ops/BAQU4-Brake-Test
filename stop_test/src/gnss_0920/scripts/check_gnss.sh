#!/usr/bin/env bash
set -u

device="${1:-/dev/ttyUSB0}"
baudrate="${2:-115200}"
duration_s="${3:-3}"

if [[ ! -e "${device}" ]]; then
  echo "[FAIL] device does not exist: ${device}" >&2
  exit 1
fi

echo "[INFO] device=${device} baudrate=${baudrate} sample_duration=${duration_s}s"
ls -l "${device}"

if [[ ! -r "${device}" ]]; then
  echo "[FAIL] device is not readable; check the dialout group (TESTING B-3)" >&2
  exit 1
fi

if ! command -v stty >/dev/null 2>&1 || ! command -v timeout >/dev/null 2>&1; then
  echo "[FAIL] this check needs stty and timeout" >&2
  exit 1
fi

if ! stty -F "${device}" "${baudrate}" raw -echo -echoe -echok; then
  echo "[FAIL] could not configure host serial port; check baudrate and permissions" >&2
  exit 1
fi

sample_file="$(mktemp -t gnss_nmea.XXXXXX)"
trap 'rm -f "${sample_file}"' EXIT

timeout "${duration_s}" cat "${device}" >"${sample_file}" 2>/dev/null || true
line_count="$(wc -l <"${sample_file}")"
echo "[INFO] captured_lines=${line_count}"
if [[ "${line_count}" -eq 0 ]]; then
  echo "[FAIL] no input; check receiver output, TX/RX, brltty and baudrate" >&2
  exit 1
fi

for sentence in GGA RMC VTG GST GSV; do
  count="$(grep -cE '^\$..'"${sentence}"',' "${sample_file}" || true)"
  echo "[INFO] ${sentence}=${count}"
done

first_gga="$(grep -m1 -E '^\$..GGA,' "${sample_file}" || true)"
if [[ -n "${first_gga}" ]]; then
  echo "[INFO] first GGA: ${first_gga}"
  latitude="$(printf '%s\n' "${first_gga}" | cut -d, -f3)"
  fraction="${latitude#*.}"
  if [[ "${latitude}" == *.* ]]; then
    echo "[INFO] latitude fractional-minute digits=${#fraction} (6+ recommended; TESTING B-5)"
  fi
fi

echo "[PASS] serial data is flowing; this script sent no receiver commands"

