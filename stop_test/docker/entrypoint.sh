#!/usr/bin/env bash
set -e

# 환경 준비만 수행한다. 센서, 인식, 제어, dashboard 노드를 시작하지 않는다.
source "/opt/ros/${ROS_DISTRO:-humble}/setup.bash"
if [ -f /workspace/install/local_setup.bash ]; then
    source /workspace/install/local_setup.bash
fi
mkdir -p /workspace/log/ros
exec "$@"

