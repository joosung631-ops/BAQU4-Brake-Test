#!/usr/bin/env bash
# Run explicitly on the HOST. Only stop_test is mounted/read; no sensor startup.
set -euo pipefail
# The driver waits for Enter at start and before releasing the brake.
if [ ! -t 0 ]; then
  echo "Run from an interactive terminal: the driver needs Enter input." >&2
  exit 2
fi
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
# Rendering runs on the host, separate from ROS/control. Check before any driving.
python3 "$task_root/stop_test/01_only_lidar/src/run_report.py" --check
output_root="$task_root/stop_test/01_only_lidar/ouput"
mkdir -p "$output_root"
run_tag="$(date +%Y%m%dT%H%M%S)-$$"
run_host="$task_root/stop_test/log/stop-test-cmd/$run_tag"
run_container="/workspace/log/stop-test-cmd/$run_tag"
mkdir -p "$run_host/src"
cp "$task_root/stop_test/01_only_lidar/src/"*.py "$task_root/stop_test/01_only_lidar/src/"*.cpp "$run_host/src/"
cp -R "$task_root/stop_test/01_only_lidar/src/control_core" "$run_host/src/control_core"
cp -R "$task_root/stop_test/src/lidar_cone/lidar_cone" "$run_host/src/lidar_cone"
cp "$task_root/stop_test/01_only_lidar/run.sh" "$run_host/run.sh"
cp "$task_root/stop_test/01_only_lidar/config.toml" "$run_host/config.toml"
cp "$task_root/stop_test/config.toml" "$run_host/speeds.toml"
docker inspect stop_test > "$run_host/container-inspect.json"
image_id="$(docker inspect --format '{{.Image}}' stop_test)"
docker image inspect "$image_id" > "$run_host/image.json"
find "$run_host/src" -type f -exec sha256sum {} + > "$run_host/source-sha256.txt"
echo "Run evidence: $run_host"
report_pid=""
stop_driver() {
  docker exec stop_test /usr/bin/python3 -c '
import os,signal,sys
from pathlib import Path
for p in Path("/proc").glob("[0-9]*"):
 try:
  args=(p/"cmdline").read_bytes().split(b"\0")
  if len(args)>1 and args[1].decode()==sys.argv[1]:os.kill(int(p.name),signal.SIGINT)
 except (FileNotFoundError,ProcessLookupError,PermissionError):pass
' "$run_container/src/run.py" 2>/dev/null || true
  touch "$run_host/driver-exited"
  if [ -n "$report_pid" ]; then
    wait "$report_pid" || echo "[stop_test] 그래프 생성 실패. $run_host/report.json과 실행 로그를 확인하세요." >&2
  fi
}
trap stop_driver EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# The atomic report.json is written only after GNSS confirms a complete stop.
# The watcher also exits cleanly if driving ends without a confirmed stop.
python3 "$run_host/src/run_report.py" --job "$run_host/report.json" \
  --done-file "$run_host/driver-exited" --output-root "$output_root" &
report_pid=$!
# Saved as a file so the terminal (not a heredoc) stays the driver's stdin.
cat > "$run_host/driver.sh" <<'RUN'
set -euo pipefail
set +u
source /opt/ros/humble/setup.bash
set -u
run_dir="$1"
core="$run_dir/src/control_core"
g++ -std=c++17 -O2 -shared -fPIC -I"$core/include" \
  "$run_dir/src/core_bridge.cpp" "$core/src/pure_pursuit.cxx" \
  "$core/src/path_geometry.cxx" "$core/src/core.cxx" -o "$run_dir/libcontrol.so"
export STOP_TEST_LIDAR_PARENT="$run_dir/src"
export STOP_TEST_VENDOR=/workspace/01_only_lidar/vendor
exec /usr/bin/python3 "$run_dir/src/run.py" --library "$run_dir/libcontrol.so" \
  --config "$run_dir/config.toml" --speeds "$run_dir/speeds.toml" --log-dir "$run_dir"
RUN
docker exec -it -e OPENBLAS_NUM_THREADS=1 -e STOP_TEST_REPO_ROOT=/workspace stop_test bash "$run_container/driver.sh" "$run_container"
