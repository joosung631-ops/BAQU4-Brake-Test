# main/src/record/record/record_node.py를 stop_test 전용으로 복사해 수정 (2026-10-28).
# 추가: 실제 데이터 수신 확인, 제동 시험 항목 입력, 녹화 중 stop_test 시험 ID 자동 기록.
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Sequence

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rosidl_runtime_py.utilities import get_message

from stop_record.config import (
    DEFAULT_PROFILE,
    DESCRIPTION_FIELDS,
    FLOW_CHECK_TIMEOUT_SEC,
    RECORD_BASE_DIR,
    RECORD_COMPRESSION_FORMAT,
    RECORD_COMPRESSION_MODE,
    RECORD_PROFILES,
    RECORD_STORAGE_FORMAT,
    STOP_TEST_RUN_DIR,
)

# 노드가 막 뜬 직후엔 DDS 디스커버리가 아직 안 끝나서 실제로 존재하는
# 토픽도 그래프에 잠깐 안 보일 수 있다. 그래서 한 번만 확인하지 않고
# 이 시간 동안 재시도한다.
TOPIC_CHECK_TIMEOUT_SEC = 3.0
TOPIC_CHECK_INTERVAL_SEC = 0.2


class RecordNode(Node):
    def __init__(self) -> None:
        # 부모 클래스(Node) 초기화
        super().__init__('record')

        # ros 파라미터 선언 - 어떤 녹화 설정(프로필)을 쓸지
        self.declare_parameter('profile', DEFAULT_PROFILE)
        profile_name = str(self.get_parameter('profile').value)

        profile = RECORD_PROFILES.get(profile_name)
        if profile is None:
            available = ', '.join(sorted(RECORD_PROFILES))
            raise ValueError(
                f"등록되지 않은 프로필이에요: '{profile_name}' (사용 가능: {available})"
            )

        topics = profile['topics']
        self.get_logger().info(
            f"ROS_DOMAIN_ID={os.environ.get('ROS_DOMAIN_ID', '0')} "
            f"ROS_LOCALHOST_ONLY={os.environ.get('ROS_LOCALHOST_ONLY', '0')} "
            f"FASTRTPS_DEFAULT_PROFILES_FILE={os.environ.get('FASTRTPS_DEFAULT_PROFILES_FILE', '(없음)')}"
        )

        # 설정된 토픽이 하나라도 없으면 녹화 자체를 시작하지 않는다
        # (실차 테스트에서 오타 하나로 빈 bag을 찍는 걸 막기 위함)
        self._ensure_topics_exist(topics)
        # 그래프에 보이는 것만으로는 부족하다: 실제 메시지가 와야 시작한다.
        self._ensure_data_flows(profile.get('flow_check', {}))

        # 토픽 확인까지는 끝났지만, 실제 녹화 시작 시점은 사용자가 직접
        # 고르게 한다 (예: 차량이 실제로 출발하는 순간에 맞춰 Enter).
        # 폴더 번호도 Enter를 누른 뒤에 계산해서, 누르지 않고 종료한 경우
        # 빈 번호가 남지 않게 한다.
        self._wait_for_start()

        output_path = self._next_run_path(profile_name)
        self.get_logger().info(
            f"녹화 시작할게요! (profile={profile_name}, output={output_path}, "
            f"topics={topics})"
        )

        self._record_and_annotate(output_path, topics, profile_name)

    def _ensure_data_flows(self, flow_check: Dict[str, str]) -> None:
        received = {topic: 0 for topic in flow_check}
        subscriptions = []
        for topic, type_name in flow_check.items():
            def count(_msg, topic=topic):
                received[topic] += 1
            subscriptions.append(self.create_subscription(
                get_message(type_name), topic, count, qos_profile_sensor_data))

        deadline = time.monotonic() + FLOW_CHECK_TIMEOUT_SEC
        while time.monotonic() < deadline and not all(received.values()):
            rclpy.spin_once(self, timeout_sec=0.1)
        for subscription in subscriptions:
            self.destroy_subscription(subscription)

        silent = [topic for topic, n in received.items() if n == 0]
        if not silent:
            self.get_logger().info(f'데이터 수신 확인: {received}')
            return
        self.get_logger().error(
            f'토픽은 보이지만 {FLOW_CHECK_TIMEOUT_SEC:g}초 동안 데이터가 오지 않아 녹화를 시작하지 않아요: '
            f"{', '.join(silent)}\n"
            '  - main 센서를 받으려면 stop_test 컨테이너를 docker-compose.sensors.yml과 함께 띄웠는지 '
            '(ROS_DOMAIN_ID=0, FASTRTPS_DEFAULT_PROFILES_FILE=fastdds-udp.xml) 확인하세요.\n'
            '  - /cmd는 stop_test 주행 노드(run.sh)가 실행 중이어야 하고, '
            '/vehicle/command_events는 trans가 /cmd를 받고 있어야 나옵니다.'
        )
        sys.exit(1)

    @staticmethod
    def _wait_for_start() -> None:
        try:
            input('\n센서 토픽 확인 완료. Enter를 누르면 녹화를 시작합니다... ')
        except EOFError:
            # 표준입력이 없는 환경(파이프 등)에서는 그냥 바로 시작
            pass

    def _ensure_topics_exist(self, topics: Sequence[str]) -> None:
        deadline = time.monotonic() + TOPIC_CHECK_TIMEOUT_SEC
        missing: List[str] = list(topics)

        while True:
            available = {name for name, _types in self.get_topic_names_and_types()}
            missing = [topic for topic in topics if topic not in available]
            if not missing:
                return
            if time.monotonic() >= deadline:
                break
            time.sleep(TOPIC_CHECK_INTERVAL_SEC)

        missing_str = ', '.join(missing)
        self.get_logger().error(
            f'다음 토픽이 없어서 녹화를 시작하지 않아요: {missing_str}'
        )
        sys.exit(1)

    @staticmethod
    def _next_run_path(profile_name: str) -> Path:
        profile_dir = Path(RECORD_BASE_DIR) / profile_name
        profile_dir.mkdir(parents=True, exist_ok=True)

        # <프로필이름>_<번호> 폴더 중 가장 큰 번호를 찾아 그다음 번호를 씀.
        # 별도 카운터 파일 대신 실제 폴더를 매번 스캔해서, 폴더를 지워도
        # 어긋나지 않게 한다.
        pattern = re.compile(rf'^{re.escape(profile_name)}_(\d+)$')
        existing_numbers = [
            int(match.group(1))
            for entry in profile_dir.iterdir()
            if entry.is_dir()
            for match in [pattern.match(entry.name)]
            if match
        ]
        next_number = max(existing_numbers, default=0) + 1
        return profile_dir / f'{profile_name}_{next_number}'

    @staticmethod
    def _record_and_annotate(output_path: Path, topics: Sequence[str], profile_name: str) -> None:
        command = [
            'ros2', 'bag', 'record',
            '-o', str(output_path),
            '--storage', RECORD_STORAGE_FORMAT,
        ]
        if RECORD_COMPRESSION_MODE != 'none':
            command += [
                '--compression-mode', RECORD_COMPRESSION_MODE,
                '--compression-format', RECORD_COMPRESSION_FORMAT,
            ]
        command += list(topics)

        # Popen + wait를 직접 써서, Ctrl+C로 우리 프로세스와 자식(ros2 bag
        # record)이 동시에 SIGINT를 받아도 자식이 완전히 종료(bag 파일
        # finalize)할 때까지 기다린 뒤에 설명을 받도록 한다.
        started = time.time()
        process = subprocess.Popen(command)
        try:
            process.wait()
        except KeyboardInterrupt:
            process.wait()
        ended = time.time()

        RecordNode._write_description(output_path, profile_name, topics, started, ended)

    @staticmethod
    def _stop_test_runs(started: float, ended: float) -> List[str]:
        # 시험 ID(폴더 이름)는 run.sh 시작 시각. 녹화보다 먼저 시작하므로, 녹화 종료 전에 시작했고
        # 녹화 시작 이후에도 commands.jsonl이 갱신된 시험을 '녹화 중 동작한 시험'으로 본다.
        runs = []
        base = Path(STOP_TEST_RUN_DIR)
        if not base.is_dir():
            return runs
        for entry in sorted(base.iterdir()):
            log = entry / 'commands.jsonl'
            try:
                run_start = datetime.strptime(entry.name.split('-')[0], '%Y%m%dT%H%M%S').timestamp()
                if run_start <= ended and log.stat().st_mtime >= started:
                    runs.append(entry.name)
            except (ValueError, OSError):
                continue
        return runs

    @staticmethod
    def _write_description(output_path: Path, profile_name: str, topics: Sequence[str],
                           started: float, ended: float) -> None:
        print('\n이 녹화에 대한 정보를 입력하세요 (그냥 엔터를 누르면 건너뜁니다).')
        answers = {}
        for key, prompt in DESCRIPTION_FIELDS:
            try:
                answers[key] = input(f'  {prompt}: ').strip()
            except EOFError:
                answers[key] = ''

        runs = RecordNode._stop_test_runs(started, ended)
        env = {name: os.environ.get(name, '') for name in
               ('ROS_DOMAIN_ID', 'ROS_LOCALHOST_ONLY', 'FASTRTPS_DEFAULT_PROFILES_FILE')}
        (output_path / 'record_info.json').write_text(json.dumps(dict(
            profile=profile_name, topics=list(topics), wall_start=started, wall_end=ended,
            stop_test_runs=runs, environment=env, **answers), ensure_ascii=False, indent=1) + '\n')

        info_section = RecordNode._build_info_section(output_path)
        lines = ['[stop_test 시험 ID (녹화 중 동작, log/stop-test-cmd/)]']
        lines += [f'  {run}' for run in runs] or ['  (없음)']
        lines += ['', '[설명]']
        for key, prompt in DESCRIPTION_FIELDS:
            lines.append(f'{prompt}: {answers[key] or "(작성 안 함)"}')
        content = info_section + '\n' + '\n'.join(lines) + '\n'
        (output_path / 'description.txt').write_text(content)

    @staticmethod
    def _build_info_section(output_path: Path) -> str:
        lines = [
            '===== 녹화 정보 (자동 생성) =====',
            f'저장 위치: {output_path}',
            '',
            '[폴더 구성]',
        ]
        for entry in sorted(output_path.iterdir()):
            lines.append(f'  {entry.name} — {RecordNode._describe_file(entry.name)}')
        # 지금 시점엔 description.txt 자신은 아직 없어서 iterdir에 안 잡히니
        # 목록에 수동으로 추가
        lines.append(f'  description.txt — {RecordNode._describe_file("description.txt")}')

        # 파일 크기/녹화 시간/시작·종료 시각/토픽별 메시지 수는 우리가 직접
        # 계산하지 않고, ros2bag 자체가 metadata.yaml을 읽어서 만들어주는
        # 'ros2 bag info' 결과를 그대로 가져다 쓴다 (재구현하면 스키마가
        # 바뀔 때마다 같이 깨질 위험이 있음).
        bag_info = subprocess.run(
            ['ros2', 'bag', 'info', str(output_path)],
            capture_output=True,
            text=True,
        ).stdout.strip()

        lines += ['', '[ros2 bag info 결과]', bag_info, '', '=' * 33, '']
        return '\n'.join(lines)

    @staticmethod
    def _describe_file(name: str) -> str:
        if name == 'metadata.yaml':
            return (
                'ros2bag이 자동 생성하는 기술 메타데이터 '
                '(토픽/타입, 메시지 개수, QoS, 압축 정보 등)'
            )
        if name == 'description.txt':
            return '이 파일 — 자동 생성된 녹화 정보 + 사용자가 입력한 설명'
        if name == 'record_info.json':
            return '분석 도구용: 프로필/토픽/녹화 시각/stop_test 시험 ID/입력 항목'
        if '.db3' in name or '.mcap' in name:
            storage = 'sqlite3 DB' if '.db3' in name else 'MCAP'
            compressed_note = ' (zstd로 압축됨)' if name.endswith('.zstd') else ''
            return f'실제 메시지 데이터 ({storage}){compressed_note}'
        return '녹화 관련 파일'


def main(args=None) -> None:
    # ros2 초기화
    rclpy.init(args=args)
    record_node = None
    try:
        # RecordNode 생성자 안에서 토픽 검사부터 녹화, 설명 저장까지 전부
        # 끝나므로, 다른 노드들과 달리 rclpy.spin()이 필요 없다 (구독/타이머
        # 콜백을 계속 처리할 일이 없음).
        record_node = RecordNode()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if record_node is not None:
            record_node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
