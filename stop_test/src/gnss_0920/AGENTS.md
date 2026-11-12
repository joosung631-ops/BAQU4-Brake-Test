# AGENTS.md — baqu4 2026 GNSS 조향 MVP

## gnss_0920 scope update (2026-09-20)

The user explicitly authorized NTRIP RTK support in this separate package.
The NTRIP exclusion below describes the original MVP, not gnss_0920.
Keep the original three /gnss/* topics and default NTRIP to disabled.
Launch credentials come from NTRIP_USERNAME and NTRIP_PASSWORD in the caller's shell.
Use package name gnss_0920 in build and launch commands; keep main/src/gnss unchanged.

> **이 파일은 구현 중 절대 어기면 안 되는 계약과 완료 기준만 담는다.** 설명·근거는 워크스페이스 루트의 `개발계획서_gnss_guidance.md`, 현장 절차는 `TESTING.md`.
>
> **배치**: `gnss_cxx`와 `guidance_cxx` **양쪽 저장소 루트에 동일한 파일로 커밋한다.** 작업 노트북은 각 저장소를 따로 clone하므로, 워크스페이스 루트에만 두면 정작 코드를 만지는 기계에 규칙이 없다.
> §1~§4는 두 저장소에 **동일하게 존재한다 — 한쪽만 고치지 말 것.**
>
> Claude Code를 함께 쓴다면 `CLAUDE.md`를 이 파일 심볼릭 링크로 둔다.

---

## 0. 이 프로젝트가 무엇인가

**내일 실차 테스트에서 "GNSS만으로 차량이 의도대로 조향되는가"를 증명하는 MVP.** 대회용 완성품이 아니다.

| 목표 | 검증 |
|---|---|
| ① 실내 — 조향·가감속·브레이크 작동 확인 | `mode:=teleop` |
| ② 실외 — 속도 일정 유지, 저장된 GNSS 경로 추종 | `mode:=record` → `mode:=follow` |

---

## 1. 범위 — P0만 구현한다

**구현한다**: 시리얼·NMEA 파싱 · ENU 변환 · COG heading · 레버암 보정 · Pure Pursuit · 안전 게이트 · UDP 출력 · 4개 모드 · `source:=file` 리플레이 · 단위 테스트 · launch · README

**구현하지 않는다** (요청 없이 추가 금지):
- NTRIP 클라이언트
- `BESTNAVA` 등 Unicore 독자 로그 파서
- IMU 상보 필터
- 차선/카메라 통합
- 경로 스무딩 (파라미터 자리만 두고 기본 OFF)
- 속도 프로파일 (조향각 비례 감속) — **속도는 상수다**

> P0 밖 기능을 "있으면 좋으니까" 추가하지 않는다. 내일 검증할 표면이 넓어질수록 원인 분리가 어려워진다.

---

## 2. 책임 분리 — 경계를 넘지 않는다

| 패키지 | 하는 일 | 하지 않는 일 |
|---|---|---|
| **`gnss_cxx`** | 시리얼 → NMEA → ENU + heading + **공분산** → `/gnss/odom` | 경로를 알지 못한다. 조향을 계산하지 않는다. **UDP 소켓을 열지 않는다** |
| **`guidance_cxx`** | 경로 소유 · Pure Pursuit · 안전 게이트 · **UDP 단독 소유** | GNSS를 직접 알지 못한다. `/localization/odom`만 구독한다 |

**★ 액추에이터 단일 소유자 원칙**: 차량에 UDP를 쓰는 프로세스는 **정확히 하나**(`guidance_node`)다. 어떤 이유로도 두 번째 송신 주체를 만들지 않는다 — 실내 테스트용 별도 노드도 안 된다.

**두 패키지 사이에 빌드 의존이 없다.** 표준 메시지로만 통신한다. **커스텀 `.msg` 금지.**

`heading` 추정(COG, 후일 IMU 융합)은 상태 추정이므로 **`gnss_cxx` 소관**이다. `guidance_cxx`는 heading을 만들지 않고 받아쓴다.

---

## 3. 인터페이스 계약

```
/gnss/odom  (nav_msgs/Odometry)  ──[launch remap]──▶  /localization/odom
  header.frame_id = "map"         ENU, datum 고정
  child_frame_id  = "base_link"   뒷차축 중심 (레버암 보정 후)
  pose.covariance = 6x6, ★반드시 채운다★
  twist.twist     = child_frame_id 기준 (body frame)
```

- 센서 노드는 **자기 이름의 토픽**(`/gnss/*`)을 낸다. 융합 결과만 `/localization/odom`이라는 고정 이름을 쓴다. 지금은 remap 한 줄로 잇는다
- `guidance_cxx`는 **`/gnss/*`를 직접 구독하지 않는다.** 나중에 융합 노드가 들어올 자리를 비워두기 위해서다
- **안전 게이트는 `fix_quality`가 아니라 `position_std = √(cov[0]+cov[7])`로 판단한다.** 소스가 GNSS가 아니게 되어도 게이트 코드가 그대로여야 한다

**공분산 경험값은 축별 σ이며 `cov`에는 σ²가 들어간다.** `position_std`는 그 **√2배**다 — 이미 √2를 곱한 값을 넣으면 두 번 부풀려진다.

| fix quality | 축별 σ | position_std |
|---|---|---|
| 4 RTK Fixed | 0.02 | 0.03 |
| 5 RTK Float | 0.3 | 0.42 |
| 2 DGPS | 0.8 | 1.13 |
| 1 SPP | 1.5 | **2.12** |
| 0 없음 | 1e6 | 1.4e6 |

### 3-1. Heading·datum 동반 계약

- yaw 유효성은 `pose.covariance[35]`로 전달한다. 유효/hold 중에는 유한한 분산을, 한 번도 얻지 못했거나 hold가 끝나면 **`1e12`**를 넣는다. `guidance_cxx`는 임의 heading을 만들지 않는다
- `record`와 `follow`는 GNSS 노드와 guidance 노드에 **같은 고정 `datum_lat/lon/alt`**를 전달한다. `Odometry`만으로는 ENU 원점의 위경도를 복구할 수 없기 때문이다
- waypoint CSV는 datum 세 값과 `frame_id`를 헤더에 보존한다. `follow` 시작 시 launch datum과 CSV datum이 다르거나 어느 한쪽이 없으면 **시작 자체를 실패**시킨다

---

## 4. 안전 — 타협 불가

### 4-1. 기본값은 항상 안전측

| 파라미터 | 기본값 | 뜻 |
|---|---|---|
| `mode` | **`idle`** | UDP 하드 차단 |
| `dry_run` | **`true`** | 모드를 바꿔도 UDP 미전송 |

**아무 인자 없이 노드를 띄우면 차가 절대 움직이지 않아야 한다.** 두 값을 모두 명시적으로 바꿔야만 움직인다. launch가 값을 주기 때문에 우연히 동작하는 상태가 되어서는 안 된다.

### 4-2. 정지 경로 — 이 구현 방식을 반드시 지킨다

```cpp
int main(int argc, char** argv) {
  rclcpp::init(argc, argv);          // rclcpp 기본 SIGINT 처리를 그대로 쓴다
  auto node = std::make_shared<GuidanceNode>();
  rclcpp::spin(node);                // Ctrl+C가 여기를 빠져나오게 함
  node->sendStopBurst();             // ★ 시그널 컨텍스트가 아님
  rclcpp::shutdown();
}
```

```cpp
void GuidanceNode::sendStopBurst() {
  if (dry_run_) return;
  Message m{};
  m.steer = 0;
  m.speed = 0;
  m.misc  = pack_misc(true, 0);                  // ★ 제동 비트 ON
  for (int i = 0; i < stop_burst_count_; ++i) {  // 기본 10회
    udp_.send(&m, sizeof(m));
    std::this_thread::sleep_for(
        std::chrono::milliseconds(stop_burst_interval_ms_));  // 기본 20 ms
  }
}
```

**⛔ 시그널 핸들러를 만들지 않는다.** 작년 `decision_cxx/src/main.cxx`의 핸들러는 결함이 셋이다 — 제동 비트 OFF · 목적지당 1회 전송 · **핸들러 안에서 힙 할당(malloc은 async-signal-safe가 아니라 데드락 시 정지 패킷이 아예 안 나간다)**. 그 패턴을 복사하지 않는다.

### 4-3. 게이트는 모드마다 다르게 적용한다

| 게이트 | `follow` | `teleop` |
|---|---|---|
| `max_position_std` / `fix_timeout` / `heading_hold_timeout` / `max_cross_track` / `timeout` | ✅ | **✗** |
| teleop 워치독 (`teleop_timeout`, 기본 1.0 s) | — | ✅ |
| SIGINT 정지 연사 · `dry_run` | ✅ | ✅ |

**`teleop`에 측위 게이트를 걸면 사람이 루프 안에 있는데도 차가 멋대로 서고, 저속 속도 매핑(TESTING E-1b)을 수행할 수 없다.**

### 4-4. 불확실하면 닫는다

- 안전 파라미터가 불확실하면 **제동 쪽으로 실패한다**(fail closed)
- 시작 직후 COG가 아직 없을 때만 최대 `heading_hold_timeout` 동안 `steer=0` 직진 bootstrap을 허용한다. 유효 heading을 한 번 얻은 뒤 localization이 yaw를 unavailable로 표시하면 두 번째 유예 없이 즉시 제동한다
- **테스트를 통과시키려고 게이트를 완화하지 않는다.** 게이트가 걸리면 원인을 찾는다
- 게이트를 추가·제거·완화하는 것은 사람의 결정이다. 에이전트가 임의로 하지 않는다

### 4-5. 사람 승인 없이 실행 금지

- **실차량으로 UDP 송신** (`dry_run:=false`)
- **GNSS 수신기 설정 변경** (`configure_on_start:=true`, `SAVECONFIG` 등)
- 이 둘은 코드에 넣되 **기본값은 항상 꺼짐**이고, 에이전트가 실행하지 않는다

---

## 5. 버그처럼 보이지만 고치면 안 되는 것

작년 `decision_cxx`에서 복사해오는 것들이다. **"개선"하지 말 것 — 펌웨어가 기대하는 동작이다.**

| 항목 | 왜 이상해 보이나 | 왜 그대로 둬야 하나 |
|---|---|---|
| `pack_misc()` 주석은 "break_on = bit 0"인데 **코드는 bit 7** | 주석과 코드가 다르다 | **펌웨어가 기대하는 것은 코드 쪽**이다. 고치면 브레이크가 안 걸린다. 주석만 "코드 기준 bit 7"로 정정 |
| `Message.steer`가 `int32_t` **도(°) 정수** | 1° 미만이 버려진다 | 프로토콜이 그렇다. `std::lround`로 반올림만 한다 |
| `Message.speed`가 **플랫폼 raw** (350/880 등) | m/s도 km/h도 아니다 | 펌웨어 단위다. raw↔m/s 매핑은 현장에서 실측한다 |
| **같은 패킷을 IP 3개에 중복 전송** | 낭비처럼 보인다 | 의도된 것이다. 목적지 목록을 줄이지 않는다 |
| `mode` 비트가 항상 0 | 안 쓰는 필드처럼 보인다 | 그대로 0으로 보낸다 |

---

## 6. `decision_cxx`와의 의도적 편차 (3건)

**나머지는 전부 작년과 동일하게 시작한다.** 아래 3건만 다르고, 각각 이유가 있다. **"원본 충실도 복원"을 이유로 되돌리지 않는다.**

| # | 편차 | 이유 |
|---|---|---|
| 1 | **정지 경로 전면 교체** (§4-2) | 원본 결함 3건 — 안전 |
| 2 | `std::lround` (원본은 절삭) | 최대 1° 손실 방지 |
| 3 | **고정 20 Hz 송신** (원본은 센서 콜백 구동 ~10 Hz) | 원본은 상류 노드가 죽으면 패킷이 아예 안 나간다. 워치독이 성립하려면 고정 주기가 필요. `tx_rate_hz`로 조정 가능 |

**프로토콜은 작년 그대로, 튜닝값은 실측으로.** 클램프·게인은 하드웨어 사실이 아니라 임무 파라미터다 — 작년 `steer` ±10° 클램프를 그대로 쓰면 최소회전반경이 5.9 m라 주차장 코너를 못 돈다.

---

## 7. 코딩 규약

- **C++17**, ROS 2 Humble
- `gnss_cxx`의 `nmea` · `geodesy`와 `guidance_cxx`의 `pure_pursuit`은 **ROS 타입을 쓰지 않는다** — ROS 없이 단위 테스트가 가능해야 한다
- 제어 상태를 **함수 지역 `static`에 보관하지 않는다** (작년 코드의 실수). 멤버로 둔다
- **매직 넘버 금지.** 현장에서 만질 값은 전부 파라미터로 빼고 마커를 단다:

```cpp
// [TUNE] lookahead 최소 거리(m). 작으면 코너를 잘 물지만 직선에서 떨린다.
//        launch: ld_min
this->get_parameter_or<double>("ld_min", ld_min_, 3.0);
```

`grep -rn "\[TUNE\]"` 한 줄로 만질 수 있는 곳이 전부 나와야 한다. **차량 IP도 여기 포함**된다 — 재컴파일 없이 바꿀 수 있어야 한다.

- D·E단계 실측값은 `guidance_cxx/config/vehicle_params.yaml`에 모으고 launch가 `params_file`로 읽는다
- **`mode`와 `state`는 다른 축이다**: `mode` = 조향 지령을 누가 만드는가(띄울 때 고정), `state` = 주행 단계(Idle/Driving/Stopping/Stopped, 실행 중 전이)

---

## 8. 완료 조건

아래가 전부 통과해야 "구현 완료"다.

```bash
# 1) 빌드 — 경고는 허용, 에러 0
colcon build --packages-select gnss_cxx guidance_cxx --symlink-install

# 2) 단위 테스트 — ROS 없이도 빌드되는 코어
colcon test --packages-select gnss_cxx guidance_cxx && colcon test-result --verbose

# 3) 하드웨어 0 리플레이 — 전 계통 구동
ros2 launch guidance_cxx follow.xml \
  source:=file \
  nmea_file:=$(ros2 pkg prefix gnss_cxx)/share/gnss_cxx/data/sample.nmea \
  waypoints:=$(ros2 pkg prefix guidance_cxx)/share/guidance_cxx/config/waypoints_example.csv \
  dry_run:=true

# 4) 안전 기본값 — 인자 없이 띄우면 mode=idle, dry_run=true
ros2 run guidance_cxx guidance_node
```

**판정 기준**

| 항목 | 통과 조건 |
|---|---|
| 단위 테스트 | `geodesy` 왕복 오차 < 1 cm · `cogToEnuYaw` 4사분면 · `nmea` 체크섬 거부 · **`pure_pursuit` 좌/우 오프셋에서 부호가 반대** ← 가장 중요 |
| 리플레이 | `/localization/odom` 약 10 Hz, `frame_id=map`, `child_frame_id=base_link`, 공분산이 채워짐 |
| RViz | 차량 pose가 `/guidance/path`를 따라 이동 |
| 조향 부호 | 직선 ≈ 0, 좌회전/우회전에서 **부호 전환** |
| dry-run | 로그에 `[DRY-RUN]` 접두어, UDP 미전송 |
| 안전 기본값 | 인자 없이 `mode=idle`, `dry_run=true` |
| `[TUNE]` | 현장에서 만질 값이 전부 마커로 노출됨 |

> **`sample.nmea`와 `waypoints_example.csv`는 한 쌍이다.** 예제 CSV는 그 NMEA 궤적을 `mode:=record`로 돌려 만들어야 datum이 일치한다. 어긋나면 3)이 통과할 수 없다.

---

## 9. 막혔을 때

- **불확실한 안전 파라미터** → 제동 쪽으로 실패시키고 사람에게 묻는다
- **P0 밖으로 나가야 할 것 같다** → 하지 말고 묻는다
- **작년 코드가 이상해 보인다** → §5를 먼저 본다. 거기 없으면 묻는다
- **테스트가 게이트에 막힌다** → 게이트를 풀지 말고 원인을 찾는다

상세 근거: 워크스페이스 루트의 `개발계획서_gnss_guidance.md` · 현장 절차: `TESTING.md`
