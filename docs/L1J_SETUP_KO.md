# L1J PC 서버 전환 안내

## 현재 준비된 상태

- upstream: `https://github.com/l1j-en/classic`
- 대상: 최종 2009 미국판 리니지 1 PC 클라이언트
- Java 17 빌드 성공: 775개 소스, `l1jen.jar`
- MariaDB 10.11.14 LTS 휴대용 구성, 로컬 포트 3307
- 게임 서버 로컬 포트 2000 기동 확인
- DB: 테이블 104개, NPC 2,747종, 몬스터 스폰 11,767개
- 월드: 맵 545개, NPC 배치 1,958개, NPC 대화 1,120개

## 실행과 종료

```powershell
powershell -ExecutionPolicy Bypass -File tools\l1j-start.ps1
powershell -ExecutionPolicy Bypass -File tools\l1j-status.ps1
powershell -ExecutionPolicy Bypass -File tools\l1j-stop.ps1
```

L1J는 `AutoCreateAccounts=True`로 설정되어 있으므로 호환 클라이언트에서 처음 입력한 계정이 자동 생성됩니다.

## 중요한 클라이언트 조건

이 서버는 기존 리니지M APK나 현재 공식 리니지 PC 클라이언트와 호환되지 않습니다. 정확히 L1J가 지원하는 최종 2009 미국판(Tikal/Antharas, S3ep1 계열) 클라이언트와 로컬 서버 주소를 지정하는 합법적인 connector가 필요합니다.

저작권이 있는 원본 클라이언트, 그래픽·음원 자료, 출처가 불분명한 사설 서버 실행 파일은 이 저장소에 포함하지 않습니다. 사용자가 적법하게 보유한 호환 클라이언트가 준비되면 `127.0.0.1:2000`에 연결해 로그인·캐릭터 생성·월드 진입을 검증합니다.

## 저장소 정책

L1J 전체 upstream 복제본, 빌드 산출물, MariaDB 바이너리와 실제 DB는 `.gitignore`로 제외됩니다. 이 저장소에는 전환 기록과 로컬 제어 스크립트만 보관합니다. L1J 자체는 GPL-2.0 조건을 따릅니다.
