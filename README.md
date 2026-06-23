# WBS → 간트차트 PNG 생성기

WBS(작업분류체계) 파일을 입력하면 Claude API가 내용을 파싱하고,
PyQt6 화면에서 미리보기/수정한 뒤 간트차트 PNG로 출력하는 데스크톱 앱.

## 목적

- 포맷이 제각각인 WBS(엑셀 표, 일정표, 스캔 이미지, PDF 등)를 사람이 직접 정리하지 않고
  Claude API로 자동 파싱해서 파트 > 소분류 > 작업(task) 구조로 통일한다.
- 파싱 결과를 PyQt6 화면에서 즉시 미리보고, 이름/날짜/색상을 수정할 수 있다.
- 확정한 결과를 디자인 스펙에 맞춘 간트차트 PNG 한 장으로 출력한다.
- 최종적으로 PyInstaller로 패키징해 Python 미설치 환경에서도 exe로 실행 가능하게 한다.

## 전체 플로우

1. 앱 실행 → Excel/JSON/이미지/PDF 중 WBS 파일 선택
2. Claude API가 파일 내용을 파싱해 파트/소분류/task/시작일/완료일 추출
   (이미지·스캔본을 넣어도 동일하게 구조화된 데이터로 변환됨)
3. 파싱 결과로 간트차트 초안을 PyQt6 화면에 미리보기
4. 사용자가 파트명/task명/날짜/색상을 표에서 직접 수정
5. 확정 → 원하는 형식으로 출력
   - PNG (이미지)
   - JSON (구조화 데이터)
   - Excel (.xlsx)
   - draw.io (.drawio) — diagrams.net에서 바로 열어 편집 가능한 도형으로 출력
6. PyInstaller로 exe 패키징해 배포

입력(Excel/JSON/이미지/PDF)과 출력(PNG/JSON/Excel/drawio) 포맷을 자유롭게 조합할 수 있다.
예: 스캔된 WBS 이미지를 넣고 → 정리된 Excel이나 JSON으로 내보내기도 가능.

## 폴더 구조

```
gantt-tool/
  main.py         # 진입점
  parser.py       # WBS 입력 파싱 오케스트레이션 (Excel/JSON/PDF/이미지 -> 구조화 데이터)
  llm_providers.py # Claude/GPT/Gemini 등 모델사별 API 호출 래퍼
  settings.py     # 프로바이더별 API 키 저장/로드 (%LOCALAPPDATA%\GanttTool\config.json)
  renderer.py     # 간트차트 렌더링 (Pillow PNG + draw.io XML 생성)
  exporter.py     # 구조화 데이터 -> JSON/Excel/drawio 내보내기
  gui.py          # PyQt6 미리보기/수정 UI + API 키 다이얼로그
  config.py       # 그리드 크기, 색상, 프로바이더 목록 등 설정값
  requirements.txt
```

## 지원 입력 포맷

| 포맷 | 처리 방식 |
|---|---|
| Excel (.xlsx, .xls) | 시트가 여러 개면 LLM이 실제 WBS 시트를 먼저 골라낸 뒤(`_select_wbs_sheet`), 명시적 시작/종료 날짜 컬럼이 있는 표 구조면 **LLM 호출 없이** 셀 좌표로 직접 추출(`_excel_table_to_dict`), 구조가 불명확하면 텍스트 LLM 파싱으로 폴백 |
| JSON | 텍스트로 변환 후 LLM 텍스트 파싱 |
| PDF | 텍스트 추출 후 LLM 텍스트 파싱 |
| 이미지 (.png, .jpg) | base64 인코딩 후 LLM Vision 파싱 |
| draw.io (.drawio) | **LLM 호출 없이** 셀 좌표(x/y/width/height)와 날짜 헤더만으로 직접 복원 |

### Excel 결정적 파싱 상세

`parser._excel_table_to_dict`는 drawio 파서와 같은 원리로 동작한다:
- 날짜 헤더 대신 "시작"/"종료" 키워드가 들어간 헤더 행을 찾는다.
- 그 왼쪽의, 데이터가 있는 컬럼들을 좌(넓은 분류)→우(좁은 분류) 순서의 계층으로 본다.
- 병합 셀로 들여쓰기한 템플릿(분류명만 있고 하위 항목이 없는 "롤업 행"으로 구간을 표시하는 방식)과
  모든 행에 파트명이 그대로 적힌 플랫 테이블 방식을 자동 감지해서 각각 다르게 처리한다.
- 날짜가 비어 있는 행도 누락시키지 않고 프로젝트 시작일로 기본값을 채워 포함한다.
- 실제 75행짜리 KT WBS 엑셀(병합 셀 4단계 들여쓰기 구조)로 검증해 75/75 완전 일치, 9개 파트로
  정확히 분리됨을 확인함. 같은 파일을 LLM 텍스트 파싱으로만 처리했을 때는 모델이 큰 표를
  요약해버려 21~50개로 누락되는 문제가 있었음 — 이게 결정적 파서를 만든 이유.

draw.io 입력은 우리 렌더러와 같은 레이아웃 규칙(라벨 영역 너비, 주 단위 그리드, 월요일 날짜 헤더)을
쓰는 drawio 파일이면 그리드 스케일을 파일에서 자체적으로 추정해 동작한다 (`parser._drawio_to_dict`).
실제 외부에서 만들어진 간트차트 drawio 파일로 검증함 — 파트 5개/phase 6개/task 40여 개가
LLM 없이 100% 정확히 복원되고 한글 라벨도 정상 렌더링됨 (`renderer._load_font`가 맑은 고딕을 우선 사용).

날짜나 구조가 모호한 경우 Claude가 주변 정보(주차, 순서 등)로 합리적으로 추론해 초안을 만든다.

## 차트 디자인 요약

- 좌측 라벨 영역(180px) + 우측 날짜 그리드(1주=38px)로 구성
- 상단: Phase 바(26px) → 월 헤더(24px) → 날짜 헤더(22px)
- 본문: 파트 헤더 행(파트 컬러) → 소분류 행(#f0f0f0) → task 행(흰 배경 + 색상 바)
- 월 경계에 점선 세로선(최상위 렌더링)
- 파트 색상은 기본 팔레트(`config.DEFAULT_PALETTE`)에서 자동 배정, 사용자가 변경 가능

## LLM 프로바이더 / API 키 관리

- WBS 파싱에 사용할 모델사를 직접 고를 수 있다 (`config.PROVIDERS` 참고):
  - **Anthropic Claude** (`claude-sonnet-4-6`) — 키 형식 `sk-ant-...`
  - **OpenAI GPT** (`gpt-4o`) — 키 형식 `sk-...`
  - **Google Gemini** (`gemini-2.0-flash`) — 키 형식 `AIza...`
  - 새 프로바이더 추가는 `config.PROVIDERS`에 항목 추가 + `llm_providers.py`에
    `validate/text/vision` 3개 함수만 구현하면 됨.
- exe/스크립트 실행 시 선택된 프로바이더의 키가 없으면 **앱이 직접 키 입력창을 띄운다**
  (취소하면 앱 종료).
- 입력한 키는 즉시 최소 토큰 더미 API 호출로 유효성을 검증한 뒤
  `%LOCALAPPDATA%\GanttTool\config.json`에 프로바이더별로 평문 저장한다 (사용자 계정별로 분리).
- 여러 프로바이더의 키를 동시에 저장해두고 필요할 때 전환할 수 있다.
- 키/프로바이더를 바꾸고 싶으면 툴바의 `API 키 변경` 버튼으로 언제든 재설정 가능.
- 프로바이더별 SDK(`anthropic`/`openai`/`google-generativeai`)는 선택해서 쓴 것만
  설치해도 동작한다 (lazy import).
- **`%APPDATA%`(Roaming)가 아니라 `%LOCALAPPDATA%`를 쓴다.** 처음엔 Roaming에 저장했는데,
  이 PC에서 `settings.clear_all()`로 지운 키 파일이 같은 옛 타임스탬프로 되돌아오는 현상을
  실제로 겪었다 (백업/EDR 에이전트가 Roaming을 동기화하는 환경으로 추정). 키처럼 이 PC를
  떠나면 안 되는 비밀값은 동기화되지 않는 LOCALAPPDATA에 두는 게 맞아서 옮겼다.

## 실행 방법

```bash
pip install -r requirements.txt
python main.py   # 최초 실행 시 API 키 입력창이 뜬다
```

## exe 패키징

저장된 키는 `%LOCALAPPDATA%\GanttTool\config.json`(런타임 사용자 설정 파일)에만 있고
이 폴더(소스 코드)에는 키가 전혀 존재하지 않으므로, PyInstaller가 패키징하는
소스 파일에는 원래부터 키가 포함되지 않는다. 그래도 개발 중 사용한 테스트 키를
실수로라도 남기지 않으려면 패키징 전에 한 번 비워두는 것을 권장:

```bash
python -c "import settings; settings.clear_all()"   # 개발용 키 전체 삭제
pyinstaller --onefile --windowed main.py
```

배포된 exe를 사용자가 처음 실행하면 키가 없으므로 `ApiKeyDialog`가 자동으로 뜨고,
사용자 본인의 키를 입력하게 된다.

## 현재 진행 상태

- [x] 데이터 모델 및 설정값 (`config.py`)
- [x] Claude API 파싱 (`parser.py`)
- [x] 간트차트 렌더러 (`renderer.py`) — 레이아웃 스펙대로 1차 수정 완료
- [x] JSON/Excel/draw.io 내보내기 (`exporter.py`)
- [x] API 키 입력/검증/저장 (`settings.py` + `gui.ApiKeyDialog`)
- [x] 멀티 LLM 프로바이더 지원 (`llm_providers.py`: Anthropic/OpenAI/Google 중 선택)
- [x] PyQt6 미리보기/편집 UI (`gui.py`) — PNG/JSON/Excel/drawio 내보내기 버튼 포함
- [x] GUI 단독 실행 확인 (PyQt6 설치 후 `ApiKeyDialog`/`MainWindow` 생성 성공)
- [x] OpenAI 키 저장 + 검증(`validate_api_key`) 성공 확인 (개발용 테스트 키)
- [x] draw.io 입력 지원 (`parser._drawio_to_dict`) — 실제 외부 drawio 파일로 전체 플로우(파싱→렌더링) 검증 완료
- [x] 한글 폰트 렌더링 버그 수정 (`renderer._load_font`가 맑은 고딕 우선 사용)
- [x] Excel/이미지(Vision)/JSON/PDF 입력 더미 데이터로 전체 플로우(OpenAI 파싱→렌더링) 검증 완료
      (JSON은 비표준 키 이름·슬래시 날짜 포맷도 정확히 정규화됨을 확인)
- [x] 이미지 입력 시 정확도 경고 다이얼로그 추가 (`gui.on_open_file`) — 행이 많은 고밀도 차트는
      Vision이 내용을 지어내는(환각) 사례를 실제 발견했음, drawio/Excel/JSON 우선 권장
- [x] LLM이 가끔 반환하는 잘못된 날짜(예: 2026-02-30) 보정 로직 추가 (`parser._sanitize_dates`)
- [x] 파트/소분류/작업 행 추가·삭제 UX (Enter=작업 추가, Delete=삭제, 우클릭 메뉴) (`gui.WBSTableWidget`)
- [x] 파트 색상 팔레트 스와치 선택 다이얼로그 (`gui.PartColorDialog`)
- [x] 라벨 텍스트 기본 굵게(draw.io fontStyle=1) 통일 — 소분류/작업명도 파트헤더·막대라벨과 동일하게
- [x] draw.io 기본 폰트(Helvetica) 반영 — Windows엔 Helvetica가 없어 메트릭이 동일한 Arial로 대체,
      텍스트에 한글이 섞이면 자동으로 맑은 고딕으로 분기 (`renderer._font_for`)
- [x] PyInstaller exe 빌드 + 실행 검증 완료 (`dist/GanttTool.exe`, 키 없을 때 다이얼로그 정상 등장)
- [x] git 저장소 생성 + GitHub push (https://github.com/hj0210/gantt-tool), `v0.1.0` 태그
- [x] 엑셀 다중 시트 자동 선택 (`_select_wbs_sheet`) — 표지/변경이력/휴일 등 제외하고 WBS 시트만 인식
- [x] 엑셀 결정적(LLM 미사용) 테이블 추출 (`_excel_table_to_dict`) — 실제 75행 WBS 파일로
      완전성(75/75) 검증, 병합 셀/플랫 테이블 두 스타일 모두 자동 감지
- [x] exe 재빌드 (행 추가/삭제, 색상 스와치, 결정적 엑셀 파서, 폰트 수정 반영된 최신 코드)
- [x] **API 키 저장 위치를 `%APPDATA%`(Roaming) → `%LOCALAPPDATA%`로 변경.** Roaming에서
      `clear_all()`로 지운 파일이 같은 타임스탬프로 되돌아오는 버그를 실제로 겪고 수정함
      (소스 실행/exe 양쪽에서 키 없을 때 다이얼로그가 정상적으로 뜨는 것까지 재검증 완료)
- [ ] 사용자가 직접 GUI를 마우스로 눌러보는 실사용 테스트 (지금까진 코드 시뮬레이션 위주)
- [ ] PDF/JSON 입력도 실제(더미 아닌) 파일로 검증 — 지금은 Excel/drawio만 실제 파일로 검증함
