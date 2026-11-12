# 라이다 콘 검출 적용

인계 자료 `lidar_cone_handoff`의 입력과 메시지 계약을 구현한 기하 기반 검출기다.
원본 `os_lidar` 축에 검출점과 관측 AABB를 겹친다. 차량 전방은 **-X**,
명목상 차량 좌측은 **-Y**이며, 이 표시 자체는 `base_link` 보정이 아니다.

## 원본 bag에 적용

저장소 루트에서 실행한다. 현재 컴퓨터의 사용자 설치 OpenCV/NumPy ABI 충돌을
피하도록 스크립트가 `/usr/bin/python3`, `PYTHONNOUSERSITE=1`을 사용한다.

```bash
bash tools/run_lidar_cones.sh

# 인계 자료의 세 샘플만 처리
bash tools/run_lidar_cones.sh \
  --samples lidar_cone_handoff/samples \
  --output test_runs/lidar-cone-20261024/samples

# 다른 bag / 구간 선택
bash tools/run_lidar_cones.sh \
  --bag 2026-10-24_7 --start 5 --duration 10 \
  --output test_runs/lidar-cone-20261024/segment
```

기본 입력은 `2026-10-24_7`, 출력은 `test_runs/lidar-cone-20261024/front_only`이다.
`cone_review.mp4`에 카메라 참고 영상, XYZ, XY, XZ와 검출 상자가 나온다.
카메라는 bag 기록 시각의 최근접 영상이며 점군을 이미지에 투영하지 않는다.
8/18/35초 PNG, 프레임별 `detections.jsonl`, `summary.json`, 설정과 명령도 저장한다.
원본 디렉터리는 읽기 전용으로 열며 zstd 해제는 자동 삭제되는 임시 디렉터리에서 한다.
ROS 재생이나 모터 명령 발행 없이 전체 bag을 분석한다.

`--config lidar_cone/config/detector.yaml`로 ROI/필터를 조정할 수 있다.
`--no-render`는 JSON만, `--no-video`는 JSON과 스냅샷만 생성한다.

기본 ROI는 전방 0~30m(`os_lidar X=-30~0`), 좌우 8m다. 30m는 초기 탐색 범위이며
센서의 최대 측정 거리나 검출 성능을 보장하는 거리가 아니다. 50m 탐색 설정은 다음과 같다.

```bash
bash tools/run_lidar_cones.sh --bag 2026-10-24_7 \
  --config lidar_cone/config/detector_50m.yaml \
  --output test_runs/lidar-cone-20261024/front_50m
```

먼 콘은 적은 점/링에 걸리므로 탐색 범위를 늘려도 동일한 검출 성능이 확보되지는 않는다.
`tools/analyze_cone_range.py`로 같은 스캔에 30m/50m 설정을 적용해 비교할 수 있다.
전체 bag에서 5스캔마다 한 번 비교한 결과는 `test_runs/lidar-cone-20261024/range_comparison`에 둔다.

## ROS 2 Humble 실행

```bash
source /opt/ros/humble/setup.bash
export PYTHONNOUSERSITE=1
export ROS_LOG_DIR="$PWD/log/lidar_cone"
colcon build --symlink-install --packages-select control_manager lidar_cone_msgs lidar_cone \
  --cmake-args -DPython3_EXECUTABLE=/usr/bin/python3
source install/setup.bash
ros2 launch lidar_cone cones.launch.py
```

- 입력: `/lidar/points`, `sensor_msgs/msg/PointCloud2`, 기본 `sensor_frame=os_lidar`.
- 상자: `/lidar/cones/markers`, `visualization_msgs/msg/MarkerArray`, 원본 센서 좌표.
  RViz Fixed Frame을 `os_lidar`로 두고 원본 PointCloud2와 MarkerArray를 함께 켠다.
  `rviz2 -d lidar_cone/config/cones.rviz`로 제공 설정을 열 수 있다.
- 제어 출력: `/sensors/detectCone`, `control_manager/msg/LidarObjects`.
- 원본 센서 3D 결과: `/perception/lidar/cones`, `lidar_cone_msgs/msg/ConeDetections3D`.
  header는 원본 측정 시각·좌표계이며 각 객체에 center/size[m], point_count가 있다.
  이 결과는 base_link 보정 없이도 유효하게 발행한다. 입력 처리 실패 시 valid=false다.
- 입력과 결과는 BEST_EFFORT/VOLATILE/KEEP_LAST(1)이다. 입력 콜백마다 한 번 처리한다.
  입력이 없으면 과거 결과를 다시 발행하지 않는다. 마커는 매 프레임 이전 상자를 지운다.

**보정값이 없을 때도 센서 좌표 검출/마커는 동작하며, 제어 출력은
원본 timestamp + `valid=false, objects=[]`다.** 예전 결과를 재사용하지 않는다.
검증된 변환으로 정상 처리했으나 콘이 없으면 `valid=true, objects=[]`다.

검증된 TF가 있으면 다음처럼 원본 측정 시각에 `base_link <- 입력 프레임`을 조회한다.

```bash
ros2 launch lidar_cone cones.launch.py transform_source:=tf
```

또는 최종 검증한 JSON을 `calibration_file:=/절대경로/calibration.json`으로 지정한다.
JSON의 `status`는 `CALIBRATED`, `source_frame`은 `os_lidar`, `target_frame`은
`base_link`, `translation_unit`은 `m`, `T_base_from_os_lidar`는 검증한 4×4 강체
변환이어야 한다. 인계 자료의 미완성/null 템플릿은 거부한다. 오프라인도
`--calibration`으로 같은 파일을 사용할 수 있다. 변환 후 **각 콘의 실제 관측점으로**
AABB 중심 `(min+max)/2`, 전체 크기 `max-min`을 다시 계산한다.

현재 저장소에는 제어 본체가 없으므로 `control_manager/`는 두 메시지만 빌드하는
독립 시험용 패키지다. 원래 차량 워크스페이스에 이식할 때는 그 패키지를 통째로
교체하지 말고, 두 `.msg`를 원래 `control_manager/msg`에 추가하고
`geometry_msgs`를 CMake/interface/package 의존성에 추가한다.
원래 `pipeline.yaml`의 `perception_types.cone`에는
`control_manager/msg/LidarObjects`를 지정한다. Object Manager의 제동 연동은
이 저장소의 검출기 범위에 포함되지 않는다.

## 검출과 결과의 의미

필드 offset/datatype/count, point_step/row_step, 엔디언을 반영해 PointCloud2를 읽고
NaN/Inf/XYZ=0을 제외한다. ROI 안에서 XY 셀의 낮은 점과 RANSAC으로 기울어진
지면을 추정한다. 지면 위의 점들을 거리 적응형 XY 연결 성분으로 분리하고
관측 높이/폭, 지면 접촉, 링 수, 조밀한 클러스터의 상하 폭으로 콘 후보를 고른다.
클러스터의 최소 점 개수는 3개이며, 링 정보가 있는 입력은 서로 다른 2개 이상의 링을 요구한다.
높은 구조물을 먼저 콘 높이로 잘라 가짜 콘으로 만드는 처리는 하지 않는다.

콘 최고점은 추정 지면의 법선 방향으로 센서보다 5cm 이상 낮아야 한다.
센서의 지면 위 높이는 매 프레임 지면 평면과 센서 원점 사이의 거리로 계산한다.
원본 센서가 기울어져 있으므로 낮은 콘도 먼 전방에서는 raw Z가 양수가 될 수 있다.
이 때문에 raw `Z<0`으로 점을 자르지 않고, 클러스터 전체를 지면 법선 기준으로 검사한다.
기본 raw Z ROI `-3~4m`에는 높은 구조물도 남겨 두고, 상자 전체를 검사해 탈락시킨다.

치수 설정은 분류 휴리스틱이며 실측 콘 치수가 아니다. 바닥 제거 후 남은 관측점의
상자를 반환하며 실물 전체 치수로 부풀리지 않는다. 희소/가림/노면 굴곡에 따른
미검출과 기둥 등의 오검출 가능성이 있다. 정답 라벨이 없어 정확도는 산출하지 않는다.
단일 스캔만 사용하며 deskew/추적/색상 분류는 구현하지 않았다.

라이다 내부 시계의 원본 `header.stamp`를 실패 때도 그대로 보존한다.
이 bag의 시계는 제어 ROS 시계와 다르므로 실차 freshness 판단에는 별도 시계 동기화가
필요하다. `1.224m`를 후륜축 기준 z 이동량으로 쓰거나 미확정 좌우/장착각을 채우지 않는다.

## 라이다 + YOLO 수동 정렬 미리보기

`custom.pt`의 파랑/노랑/빨강 박스 위에 라이다 콘 클러스터와 중심을 투영한다.
카메라가 라이다 아래에 있다고 가정한 초기값은 `config/fusion_preview.json`에 있다.
화각 80도, 높이 차이 20cm, yaw -2도, pitch +4도, roll -1도는 **시각화용 추정값**이다.

```bash
# 8/18/35초의 세 샘플: YOLO 추론, 투영 이미지와 조절용 데이터 저장
bash tools/run_fusion_preview.sh

# 저장한 샘플을 슬라이더 창으로 열기. YOLO를 다시 실행하지 않는다.
bash tools/run_fusion_preview.sh \
  --review test_runs/fusion-preview-20261024/samples --gui

# 전체 bag을 10Hz로 처리하고 영상 생성
bash tools/run_fusion_preview.sh --bag 2026-10-24_7 \
  --output test_runs/fusion-preview-20261024/bag_10hz

# 저장한 전체 bag을 슬라이더 창으로 열기
bash tools/run_fusion_preview.sh \
  --review test_runs/fusion-preview-20261024/bag_10hz --gui
```

슬라이더로 프레임, 화각, 높이 차이, yaw/pitch/roll, 카메라의 좌우·전후 위치,
영상 중심을 바꿀 수 있다. 실제 각도와 높이는 영상 하단에 표시한다.
양의 yaw는 점을 오른쪽, pitch는 아래쪽, roll은 시계 방향으로 움직인다.
`Camera shift`는 **준비한 프레임 간격**만큼 카메라 영상과 YOLO 결과를 함께 옮긴다.
기본 bag 처리에서는 한 칸이 약 100ms이며 `--stride`를 바꾸면 간격도 달라진다.
양수는 더 나중 카메라 영상을 고른다. 캐시 끝에서는 가장 가까운 영상을 유지하고
실제 시각 차이와 `camera_shift_clamped`를 기록한다.

- `A`/`D`: 이전/다음 프레임, `Space`: 재생/정지.
- `P`: 주변 라이다 점 표시/숨기기.
- `S`: 현재 설정, 현재 PNG, `current_matches.json` 저장.
- `V`: 현재 설정으로 전체 PNG/매칭 결과/MP4 다시 생성.
- `Q` 또는 창 닫기: 설정을 저장하고 종료. 전체 결과 반영은 `V`를 누른다.

십자와 점은 라이다 검출 결과다. YOLO와 연결된 점은 해당 콘 색상,
연결되지 않은 점은 자홍색이다. `L번호` 뒤의 거리는 원본 센서 XY 평면의 거리다.
멀리 있는 작은 콘은 글자 겹침을 줄이기 위해 점/십자/박스만 표시한다.
투영 중심이 YOLO 박스에 기본 10px 여유를 준 범위에 있을 때만 일대일 연결하며,
`matched`는 이 기하 조건을 통과한 수이지 검출 정확도가 아니다.

출력에는 `*_overlay.png`, bag의 `fusion_review.mp4`, `fusion_matches.jsonl`,
`summary.json`, `preview_settings.json`, 재사용용 `frames.json`과 `frames/`가 있다.
`--review`에는 `frames.json`이 있는 폴더를 지정한다. 창을 열려면 GUI 디스플레이가 필요하다.
저장한 설정은 `--projection 경로/preview_settings.json`으로 다른 실행에도 적용할 수 있다.

`--start 5 --duration 10`, `--stride 2`, `--max-frames 50`, `--no-video`로 처리량을 줄인다.
bag의 `--camera-offset-ms 50`은 각 라이다 기록 시각보다 50ms 뒤를 기준으로 카메라를
고르므로 GUI의 프레임 이동보다 세밀하게 조정할 수 있다. 샘플 JPEG는 고정된 쌍이다.

시간 연결은 센서마다 서로 다른 `header.stamp`를 직접 비교하지 않고 bag 기록 시각을 쓴다.
추정 투영은 렌즈 왜곡을 보정하지 않으며, 가까운/먼 콘과 화면 양쪽을 함께 확인해야 한다.
이 설정은 `APPROXIMATE_PREVIEW`로 저장되며 `os_lidar -> base_link` 보정 파일과 별개다.

## 검증

```bash
source /opt/ros/humble/setup.bash
source install/setup.bash
PYTHONNOUSERSITE=1 /usr/bin/python3 -m pytest -q lidar_cone/test
```

점군 메모리 배치/원본 CDR 일치, 기울어진 합성 노면과 콘/기둥 분리, AABB/강체 변환,
원본 timestamp와 빈 결과/실패 계약을 검증한다. 실제 bag의 성능/결과는 출력 폴더의
`summary.json`을 참조한다.
