# gnss_0920

기존 `gnss`에 2026-09-20 v3 NTRIP 지원을 적용한 별도 ROS 2 패키지입니다.
좌표 변환, heading, 레버암 보정, 공분산 계산과 출력 토픽은 기존 방식입니다.

## 빌드 및 RTK 실행

호스트에서 `docker compose exec main bash`로 컨테이너에 들어간 뒤 실행합니다.
기존 패키지와 구분하기 위해 실행 명령의 패키지명은 `gnss_0920`입니다.

```bash
source /opt/ros/humble/setup.bash
cd /workspace
colcon build --packages-select gnss_0920 --symlink-install
source install/setup.bash

export NTRIP_USERNAME='<ID>'
export NTRIP_PASSWORD='<PW>'
ros2 launch gnss_0920 gnss.xml ntrip_enabled:=true
```

계정은 launch를 실행하는 같은 터미널에서 입력합니다. launch는 이를 노드의
환경변수로 전달하므로 코드나 설정 파일에 실제 계정을 저장할 필요가 없습니다.
직접 입력한 export 명령은 셸 설정에 따라 히스토리에 남을 수 있습니다.

수신기 기본값은 `/dev/ttyUSB0`, 115200 baud입니다. 컨테이너에서 장치에 접근할
수 있어야 하며 PC에는 인터넷이 필요합니다. 휴대폰 테더링이나 핫스팟을 사용할
수 있습니다. 노드가 보정 서버에서 RTCM을 받아 같은 시리얼로 수신기에 보냅니다.

| 설정 | 기본값 |
|---|---|
| `ntrip_enabled` | `false` |
| `ntrip_host` | `RTS1.ngii.go.kr` |
| `ntrip_port` | `2101` |
| `ntrip_mountpoint` | `RTK-RTCM32` |
| `ntrip_gga_interval` | 5초 |
| `ntrip_gga_max_age` | 10초 |
| `ntrip_connect_timeout` | 5초 |
| `ntrip_data_timeout` | 10초 |
| `ntrip_reconnect_delay` | 5초 |

유효한 위치를 얻으면 접속합니다. `CONNECTED-NO-DATA`는 로그인 후 보정 무수신,
`OK`는 보정 수신, `NO-DATA`는 수신 중 3초 초과 중단을 나타냅니다.
RTK 고정 여부는 별도로 `FIX RTK-FIX` 또는 `/gnss/status` 값 4로 확인합니다.
수신기 설정 변경(`configure_on_start`)은 기본적으로 꺼져 있습니다.

## 출력

| 토픽 | 메시지 | 내용 |
|---|---|---|
| `/gnss/odom` | `nav_msgs/msg/Odometry` | ENU 위치, heading, 차량 기준 속도, 공분산 |
| `/gnss/fix` | `sensor_msgs/msg/NavSatFix` | 위도, 경도, 고도, 위치 공분산 |
| `/gnss/status` | `std_msgs/msg/UInt8` | 0 미측위, 1 SPP, 2 DGPS, 4 RTK Fixed, 5 RTK Float |

`map` 기준의 `base_link`는 레버암 보정 후 뒷차축 중심입니다.
heading은 이동 방향으로 추정하며 IMU 융합은 없습니다.
기준점은 `datum_lat`, `datum_lon`, `datum_alt`로 지정할 수 있습니다.
경로 기록과 추종에는 동일한 고정 기준점을 사용해야 합니다.

```bash
ros2 topic echo /gnss/odom --once
ros2 topic echo /gnss/fix --once
ros2 topic echo /gnss/status --once
```

기존 `gnss`와 동시에 실행하면 같은 장치와 토픽을 사용하므로 하나만 실행하세요.
기존 `gnss_tools` launch는 여전히 원래 `gnss`를 실행합니다.
이 패키지는 조향 계산이나 차량 UDP 송신을 하지 않습니다.

## 장비 없는 리플레이와 테스트

```bash
ros2 launch gnss_0920 gnss.xml source:=file \
  nmea_file:=$(ros2 pkg prefix gnss_0920)/share/gnss_0920/data/sample.nmea
colcon test --packages-select gnss_0920
colcon test-result --verbose
```

파일 리플레이에서는 NTRIP가 비활성화됩니다. 실제 보정 수신과 RTK 고정은
장비와 계정, 야외 수신 환경에서 별도로 확인해야 합니다.
