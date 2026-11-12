# encoder_motor

수신 전용 패키지. 제어 UDP를 보내지 않는다. 실행 명령은 그대로 유지한다.

```bash
ros2 run encoder_motor motor_rpm
ros2 run encoder_motor steer_angle
```

## 입력과 출력

| 노드 | UDP 입력 (little-endian) | ROS 출력 |
|---|---|---|
| motor_rpm | `10.177.21.2:5001` → PC `:5001`, **8바이트 `<iI>`** | `/motor_feedback`, `encoder_motor/msg/MotorFeedback` |
| steer_angle | `10.177.21.4:5000` → PC `:5002`, 기존 6바이트 `<hI>` | `/steering_feedback`, `encoder_motor/msg/SteeringFeedback` |

`MotorFeedback`: `int32 motor_rpm`, `uint32 motor_rpm_mcu_ms`, `bool motor_rpm_valid`.
`SteeringFeedback`: `float32 steer_angle` (degree), `uint32 steer_angle_mcu_ms`,
`bool steer_angle_valid`. 각 메시지의 세 필드는 같은 UDP 샘플을 나타낸다.

이전 `/motor_rpm`, `/motor_rpm_valid`, `/steer_angle`, `/steer_angle_mcu_ms`,
`/steer_angle_valid` 토픽은 더 이상 발행하지 않는다. 출력 이름은 각 노드의
`feedback_topic` ROS 파라미터로 변경할 수 있다.

모터는 **새 8바이트 펌웨어용**이다. 이전 `<iB>` 5바이트 패킷은 경고 후 버린다.
RPM은 부호를 그대로 보존한다(현재 보드 기준 전진 음수). 조향은 기존
`sign` 파라미터(기본 `1`, 허용값 `-1` 또는 `1`)만 적용하며 직진 영점을 추정하지 않는다.
Sensor Interface / Global State Estimator / trans / 펌웨어는 이 변경에 포함하지 않는다.

2026-10-23 실제 RPM 펌웨어와 연결할 때 `motor_rpm`은 UNO에서 GNSS 기준으로
보정한 정수 RPM이다. PC 수신부는 추가 배율을 곱하지 않는다. 과거 시험 로그의
컨트롤러 원본 RPM과 구분하며, 8바이트 형식과 MCU tick/valid 계약은 유지한다.

## 시각과 유효성 계약

- 모터 timestamp는 **마지막 CAN RPM을 수신한 MCU tick(ms)**이다. UDP 송신 시각이 아니다.
  새 CAN 측정이면 RPM 값이 같아도 tick이 진행해야 한다. 수신 목표 20 Hz는
  펌웨어에서 설정하며 PC는 정상 패킷을 받을 때마다 발행한다.
- 두 MCU의 시계는 서로 및 ROS 시각과 동기화되지 않는다. `*_mcu_ms`를 ROS
  timestamp로 간주하거나 두 장치의 tick을 직접 비교하면 안 된다.
- PC는 `time.monotonic()`으로 마지막 정상 패킷 수신과 마지막 MCU tick 변경의
  경과시간을 각각 관리한다. 기본 모터 0.5초 / 조향 0.1초를 넘으면 무효화한다.
  같은 tick의 패킷을 반복 수신해도 측정의 유효기간을 갱신하지 않는다.
- 수신 중단 시 마지막 값·tick을 보존한 **valid=false 메시지를 한 번** 발행한다.
  첫 측정 전 timeout이면 기본값 0/0과 false를 보낸다. 이는 정지 측정값이 아니다.
  구독자는 자체 timeout도 관리해야 한다(무효 알림 전에 연결되었다는 보장이 없음).
- MCU uint32 tick 순환을 허용한다. 역행 시 재부팅/패킷 순서 이상을 경고하고
  새 tick 기준으로 수신을 계속한다. `valid=true`는 패킷·진행 시각이 유효하다는
  뜻이며, 조향 영점·서보 상태·CAN 센서 건강 상태가 검증됐다는 의미가 아니다.
- 새 모터 UDP에는 MCU valid 비트가 없다. 펌웨어는 CAN 무효 시 송신을 중단하거나
  마지막 측정 tick을 유지해야 한다. 무효 RPM에 새 timestamp를 붙여 보내면 PC는
  이를 구별할 수 없다. RPM=0 또는 tick=0을 임의의 무효 표식으로 사용하지 않는다.

## 빌드

메시지를 같은 패키지에서 생성하기 위해 build type을 `ament_cmake`로 전환했다.
추가 메시지 패키지나 다른 소스 디렉터리 변경은 없다. 이전 Python 빌드와
생성물을 섞지 않도록 새 build/install 경로에 빌드한다(main 컨테이너 안).

```bash
cd /workspace
source /opt/ros/humble/setup.bash
source /workspace/install/setup.bash
colcon --log-base src/encoder_motor/log/feedback build \
  --base-paths src/encoder_motor --packages-select encoder_motor \
  --build-base src/encoder_motor/build/feedback \
  --install-base src/encoder_motor/install/feedback --symlink-install
source /workspace/src/encoder_motor/install/feedback/setup.bash
```

다른 패키지와 같은 프로세스에서 사용할 때도 위 overlay를 source해야 새 타입을 찾는다.
새 터미널에서도 Humble → workspace → encoder_motor overlay 순서로 source한다.

```bash
ros2 interface show encoder_motor/msg/MotorFeedback
ros2 interface show encoder_motor/msg/SteeringFeedback
ros2 topic echo /motor_feedback
ros2 topic echo /steering_feedback
```

Sensor Interface에서 이 타입을 구독·relay하도록 하는 작업은 별도이며 아직 적용하지 않았다.
