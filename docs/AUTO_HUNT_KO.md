# LDPlayer 자동사냥 안전 도구

> 이 문서는 초기 설계 개요입니다. 현재 운영 상태와 정확한 실행 절차는
> [AUTO_HUNT_STATUS_KO.md](AUTO_HUNT_STATUS_KO.md)를 우선 참고하세요.

이 도구는 개인 로컬 서버의 1280×720 LDPlayer 화면을 ADB로 읽습니다. 게임
프로세스에 코드를 주입하거나 메모리를 읽지 않습니다.

## 판정 방식

현재 판정은 전용 PK 표시와 저체력 조건을 함께 사용합니다. 다음 내용은 초기
화면 신호 설계의 배경으로 보존합니다.

1. 2.5초 안에 HP 바가 8% 이상 감소
2. 월드 화면에 파란색/청록색 플레이어 이름 신호가 충분히 존재
3. 현재 위치가 Safety Zone으로 표시되지 않음

판정 순간의 화면은 `data/bot-evidence`에 저장됩니다. 현재 두 LDPlayer 모두
실제 조작이 활성화되어 있습니다.

파란 스킬 이펙트도 일부 감지될 수 있으므로 기본 임계값은 현재 두 실제
화면에서 측정한 값에 맞춰 보수적으로 설정했습니다. 피격 시험 화면을 확보한
뒤 증거 이미지와 로그를 기준으로 최종 조정합니다.

## 현재 화면 측정

```powershell
& 'C:\Users\k1j1s\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' `
  tools\ldplayer_auto_hunt.py --once
```

## 감지 모드

플레이어마다 별도 터미널에서 실행합니다.

```powershell
& 'C:\Users\k1j1s\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' `
  tools\ldplayer_auto_hunt.py --device emulator-5554
```

두 번째 플레이어는 `emulator-5556`을 사용합니다. `Ctrl+C`로 즉시
정지합니다.

두 플레이어를 백그라운드 감지 모드로 한 번에 시작하거나 종료하려면 다음을
사용합니다.

```powershell
powershell -ExecutionPolicy Bypass -File tools\auto-hunt-start.ps1
powershell -ExecutionPolicy Bypass -File tools\auto-hunt-stop.ps1
```

## 실제 조작 활성화 전 확인

`config/auto_hunt.json`의 다음 좌표는 각 캐릭터 UI에서 반드시 확인해야
합니다.

- `return_actions`: 귀환 주문서가 배치된 단축 슬롯
- `fixed_town_actions`: 즐겨찾기 5번째 기란마을 고정 이동
- `town_actions`: 자동 보관·모두 맡기기와 주홍 물약 직접 구매
- `hunting_routes`: 축순 첫째·둘째 기억 장소 교대와 AUTO 재개

전체 실행을 일시 정지하려면 `dry_run`을 `true`로 바꿉니다. 캐릭터별 실제
조작 여부는 `actions_enabled`로 제어합니다. 잘못된 귀환 슬롯이나 목적지
좌표로 인한 아이템 사용을 막기 위해 검증 전 캐릭터는 활성화하지 마십시오.
