# stop_test 워크스페이스

`main/`과 같은 위치의 독립 시험 워크스페이스다. main에서 GPS 추종·차량 제어와
센서 드라이버 소스를 복사하고, 라이다 ZIP에서 콘 인식 패키지를 가져왔다.
콘의 거리/웨이포인트에 따른 정지 판단은 아직 구현하지 않았다.

기존 `baqu4-main:humble` 이미지의 ROS 2 Humble, Python, colcon을 재사용한다.
별도의 이미지 빌드는 필요 없다. 루트의 `docker-compose.yml`과 기존 main/dashboard
컨테이너 설정은 변경하지 않는다.

## 시작과 접속

호스트에서 실행한다.

```bash
cd ~/Workspaces/2026WS/stop_test
docker compose up -d stop_test
docker compose exec stop_test bash
```

컨테이너의 `/workspace`는 호스트의 `2026WS/stop_test/`만 연결한다.
이미지 기본 사용자 `dev`는 현재 호스트와 동일한 UID/GID 1000:1000이다.
대화형 bash에서도 이미지의 bashrc가 ROS와 현재 워크스페이스 환경을 불러온다.

```text
stop_test/
  docker-compose.yml      # 독립 Compose 프로젝트 stop-test
  docker/entrypoint.sh    # ROS 환경 준비만 수행
  src/                    # 복사한 제어·센서·콘 인식 소스
  config/                 # 비어 있음: 추후 시험 설정용
  maps/                   # MAP_test.json을 추후 이곳에 넣음
  log/                    # ROS 로그와 환경 점검 기록
```

별도 `.env` 없이 Compose 기본값인 이미지 `baqu4-main:humble`과 ROS 도메인 `87`을
사용한다. 필요하면 `docker-compose.yml`의 기본값 또는 호스트 환경변수
`STOP_TEST_IMAGE`, `STOP_TEST_ROS_DOMAIN_ID`로 변경한다.
추후 빌드할 때 생성되는 `build/`, `install/`, `log/`도 이 폴더에만 남는다.
기존 main의 `install/setup.bash`를 source하거나 main을 `/workspace`에 마운트하지 않는다.

## 가져온 소스와 지도 경로

- main: `control_manager`, `encoder_motor`, `vehicle_recorder`, `trans`,
  `gnss_0920`, `lidar`, `ouster-ros`.
- 라이다 ZIP: `lidar_cone`, `lidar_cone_msgs`, 보정 템플릿과 검증용 샘플인
  `lidar_cone_handoff`.
- `monitor_1021`과 기존 지도, 빌드 결과, 주행 로그는 복사하지 않았다.
- ZIP의 메시지용 `control_manager`는 따로 넣지 않고, 인계 패치의 메시지와
  빌드 의존성만 제어 본체 복사본에 추가했다. 인식/정지 스위치는 원본대로 유지한다.

사용자가 만들 지도의 호스트 경로는 `stop_test/maps/MAP_test.json`, 컨테이너 경로는
`/workspace/maps/MAP_test.json`이다. `test`와 `brake_inspection` 모드에서 이 파일을
참조하도록 수정했다. 현재 지도 파일과 대체 지도는 없다.

지도는 기존 로더가 사용하는 `gps-final-map` version 1, `rear_axle_center` 형식이어야
한다. 새 지도에 맞는 진행 추적 프로필은 아직 정하지 않았으며, 두 시험 모드의
`route_progress_enabled: false`는 원본 그대로다. 복사된 예선/본선 모드는 기존 지도
경로와 전용 프로필을 유지하므로 이번 시험에는 사용하지 않는다.

센서 실행 전에 GNSS USB 장치 매핑, 라이다 차량 좌표 보정과 시각 동기화가 필요하다.
`trans` 원본 설정은 실제 UDP 송신이 가능하므로 소스 확인/빌드 중 실행하지 않는다.
복사한 `vehicle_recorder`도 기록 노드를 실행할 때만 녹화한다.

## 통신과 장치

- 기본 ROS 도메인은 `87`이며 현재 main의 `0`과 다르다.
- `ROS_LOCALHOST_ONLY=1`로 ROS discovery를 이 호스트로 제한한다.
- Ethernet 센서를 위한 host 네트워크는 준비하지만 센서 드라이버는 실행하지 않는다.
- USB 장치, GPU, main 소스·bag, Docker 소켓은 연결하지 않는다.
- 이 설정만으로 main 센서 토픽을 구독할 수는 없다. 향후 센서 공유 시 도메인과
  장치 담당 노드를 정하고 연결한다. ROS 도메인은 직접 UDP 차량 명령을 차단하는
  네트워크 방화벽은 아니다.

환경 준비 확인은 다음처럼 할 수 있다. 어떤 ROS 노드도 시작하지 않는다.

```bash
docker compose exec stop_test bash -lc 'printenv ROS_DISTRO ROS_DOMAIN_ID ROS_LOCALHOST_ONLY; command -v ros2 colcon'
```

## 제동 시험 녹화 (`stop_record`)

main의 `record`를 복사해 만든 stop_test 전용 녹화 패키지다(`src/stop_record/`).
stop_test 컨테이너 안에서 main 컨테이너의 센서 토픽과 stop_test의 `/cmd`를 함께 녹화한다.
저장 위치는 호스트 `stop_test/bags/<프로필>/<프로필>_<번호>/`다.

main 센서를 받으려면 컨테이너가 **센서 공유 설정**(`docker-compose.sensors.yml`: 도메인 0,
FastDDS UDP 전용)이어야 한다. 기본 설정(도메인 87)이나 도메인 0 + 기본 전송에서는 토픽이 보여도
데이터가 오지 않는다(`test_runs/sensor-cross-container-check-20261027T221017+0900/`).
그래서 녹화 전에 주요 토픽이 3초 안에 실제로 수신되는지 확인하고, 아니면 시작하지 않는다.

```bash
# 호스트 프로젝트 루트에서 (센서 공유 설정으로 컨테이너 준비)
docker compose -f stop_test/docker-compose.yml -f stop_test/docker-compose.sensors.yml up -d --no-build stop_test
docker exec -it stop_test bash
ros2 run stop_record record                                        # brake_test (기본, 카메라/IMU 없이)
ros2 run stop_record record --ros-args -p profile:=brake_test_core # 카메라/IMU/송신 이벤트 없이
```

- 실행 순서: main 센서 → `trans` → `01_only_lidar/run.sh`(엔터 대기 중에도 `/cmd` 발행) →
  녹화 → 녹화 엔터 → 주행 엔터. 목록의 토픽이 하나라도 없으면 녹화를 시작하지 않는다.
- `brake_test`: 라이다 점군/메타데이터, GNSS, 모터/조향 피드백, `/tf_static`,
  `/cmd`, `/vehicle/command_events`(trans UDP 송신 시각).
  `brake_test_core`: 라이다 점군/메타데이터, GNSS, 모터 피드백, `/tf_static`, `/cmd`만.
- 두 프로필 모두 카메라와 IMU(`/lidar/imu` 포함) 없이 녹화한다.
  관련 토픽과 IMU 수신 확인은 `src/stop_record/stop_record/config.py`에 주석으로 보존했다.
  다시 사용하려면 해당 주석을 해제하고 `colcon build --packages-select stop_record`로 재빌드한다.
- Ctrl-C로 끝내면 펌웨어, 1028 `set` 값, 줄자로 잰 정지 간격, 메모를 묻는다.
  녹화 중 동작한 stop_test 시험 ID(`log/stop-test-cmd/`)는 자동으로 적는다.
  같은 내용을 분석용 `record_info.json`으로도 남긴다.
- main의 `ros2 run record record`와 동시에 녹화하지 않는다(같은 데이터를 두 번 받음).
- 커스텀 메시지 타입 지원을 위해 `encoder_motor`, `vehicle_recorder`, `stop_record`만
  colcon 빌드했다(`build/`, `install/`). 소스를 바꾸면 컨테이너 안에서
  `colcon build --packages-select encoder_motor vehicle_recorder stop_record`로 다시 빌드한다.
- 브레이크 보드 시리얼 로그(액추에이터 위치, 압력)는 ROS 토픽이 아니라 이 녹화에 포함되지 않는다.

## 종료와 격리 시험

```bash
# 컨테이너를 남기고 정지
docker compose stop stop_test

# 자동 시험은 같은 이미지/마운트를 사용하는 임시 컨테이너로 실행 후 삭제
docker compose run --rm --no-deps -T stop_test bash -lc 'command -v ros2 colcon'
```

실제 주행은 기존 운용 정책에 따라 main을 사용한다. 이 컨테이너는 환경 준비와
독립 검증용이다. 시험별 로그·명령·설정·코드 버전·이미지 정보는 호스트에 보존한다.
컨테이너 삭제 전에는 `docker diff stop_test`, Docker 로그와 설정을 확인·보존한다.
호스트에 마운트된 파일은 컨테이너 삭제 후에도 유지된다.
