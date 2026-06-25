# 작업 인계 노트 (2026-06-25 기준)

새 대화/세션에서 이어가기 위한 메모. README.md의 체크리스트가 "뭘 했는지" 정리라면,
이 문서는 "지금 뭘 더 고쳐야 하는지 + 왜 이렇게 했는지" 위주.

## 현재 버전

- git: `v0.3.0` 태그 (커밋 `634474e`까지 push됨)
- exe: `dist/GanttTool.exe` (최신 코드 반영, 그리드 범위 버그 수정 포함)

## 지금 안 끝난 것 / 다음에 할 일

1. **API 키를 아직 안 지운 상태로 둠** — 사용자가 "일단 쓰자, 나중에 안정화되면 지우겠다"고
   결정함. `%LOCALAPPDATA%\GanttTool\config.json`에 실제 사용 중인 키가 들어있을 수 있음.
   **배포/공개 전에는 반드시 `settings.clear_all()`로 비울 것.**
2. 사용자가 "아직 수정해야 할 게 많다"고 했음 — 구체적으로 뭔지는 다음 대화에서 사용자에게
   직접 물어볼 것 (이 메모 작성 시점엔 아직 안 들음).
3. README.md에 보류 중으로 남아있는 것: 다중 문서/탭, "보기" 메뉴(확대/축소 등).
   필요해지면 진행.
4. 차트 드래그 편집(추가/이동/리사이즈)의 실시간 시각 피드백(고무줄 표시)은
   1차 버전에서 생략함 — 지금은 마우스 떼는 순간에만 결과가 보임.

## 최근에 잡은 진짜 버그들 (재발 방지용 기록)

- **그리드 범위가 실제 작업 날짜를 못 따라가던 버그** (커밋 `634474e`): `WBSData.project_start/end`는
  작업을 추가/날짜수정해도 자동 갱신 안 됨. "새로 만들기"가 오늘~+7일로 그리드를 고정해버려서,
  그 범위 밖 날짜의 작업 막대가 음수 x좌표로 계산돼 라벨 영역에 겹치거나 화면 밖으로 사라짐.
  → `GanttRenderer.__init__`에서 항상 실제 작업 날짜로 그리드 범위를 재계산하도록 고침.
- **미리보기 차트 클릭 좌표 버그** (커밋 `7e4a8e8`): `QScrollArea.setWidgetResizable(True)`
  때문에 라벨이 뷰포트를 채우려고 pixmap보다 커지면서 이미지가 가운데 정렬됨 → 클릭 좌표와
  이미지 픽셀 좌표가 어긋남. `False`로 고침. (디버깅 시 2점 캘리브레이션으로 원인 찾음 —
  스크린샷 좌표와 앱이 실제로 받는 좌표가 다를 수 있다는 걸 기억해둘 것.)
- **API 키 저장 위치 버그** (커밋 `cdf0015`): `%APPDATA%`(Roaming)는 이 PC에서 백업/EDR
  에이전트가 동기화하는 것으로 추정되어, 지운 파일이 같은 타임스탬프로 되돌아오는 현상
  발생. `%LOCALAPPDATA%`로 옮김 (보안상으로도 이게 맞음 — 비밀값은 동기화 안 되는 곳에).
- **설정 파일 BOM 문제** (커밋 `0813bb6`): PowerShell로 만든 테스트 파일에 UTF-8 BOM이
  붙어서 `json.loads()`가 조용히 실패 → 빈 설정으로 폴백. `utf-8-sig`로 읽도록 방어.
- **LLM이 큰 엑셀 표를 요약/누락시키는 문제**: 75행짜리 실제 WBS 엑셀에서 21~50개만
  추출되는 걸 발견. → drawio처럼 좌표 기반 결정적 파서(`parser._excel_table_to_dict`)를
  만들어서 LLM 없이 100% 정확하게 추출하도록 변경 (시작/종료일 컬럼이 명확한 경우).

## 디버깅 환경 특이사항 (다음 세션에서 또 헷갈리지 않도록)

- 이 PC의 bash `python`은 **Microsoft Store(MSIX) 패키지 버전**이라, `%LOCALAPPDATA%`
  쓰기가 자동으로 가상화된 별도 경로로 리다이렉트됨. bash-python으로 설정 파일을
  테스트할 때 실제 exe가 보는 파일과 다른 파일을 보고 있을 수 있음 — 헷갈리면
  PowerShell의 `Test-Path`/`Get-Content`로 진짜 경로를 직접 확인할 것.
- computer-use 스크린샷 좌표 ≠ 항상 앱이 받는 좌표 1:1 아님. 클릭이 이상하게 안 먹히면
  먼저 의심할 것: (1) 앱 창이 실제로 frontmost인지, (2) QScrollArea/레이아웃이 위젯을
  실제 크기보다 늘리고 있는지.
- `gh` CLI, GitHub 계정 `hj0210`으로 인증 완료된 상태. 저장소: https://github.com/hj0210/gantt-tool

## 폴더 구조 / 핵심 파일 (README.md에 더 자세히 있음)

```
gantt-tool/
  main.py / gui.py / parser.py / renderer.py / exporter.py
  llm_providers.py / settings.py / config.py
  requirements.txt, README.md, HANDOFF.md(이 파일)
```

## 새 대화 시작할 때 추천 멘트

> "C:\Users\KTDS\gantt-tool 프로젝트야. README.md랑 HANDOFF.md 읽고 지금 상태 파악해줘."
