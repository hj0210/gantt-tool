"""WBS 간트차트 렌더링 설정값"""

# ---- 캔버스 / 그리드 ----
LABEL_WIDTH = 180          # 좌측 라벨 영역 width
WEEK_WIDTH = 38            # 1주 = 38px
GRID_BORDER_COLOR = "#eeeeee"
BACKGROUND_COLOR = "#ffffff"

# ---- 상단 헤더 ----
PHASE_BAR_HEIGHT = 26      # Phase 바, y=0
MONTH_HEADER_HEIGHT = 24   # 월 헤더, y=26
MONTH_HEADER_BG = "#f8f9fa"
DATE_HEADER_HEIGHT = 22    # 날짜(M/D) 헤더, y=50
DATE_HEADER_Y = 50

HEADER_TOTAL_HEIGHT = PHASE_BAR_HEIGHT + MONTH_HEADER_HEIGHT + DATE_HEADER_HEIGHT  # 72

# ---- 본문 행 ----
PART_HEADER_HEIGHT = 26
PART_COLORBAR_WIDTH = 8
SUB_ROW_HEIGHT = 26
SUB_ROW_BG = "#f0f0f0"
SUB_ROW_FONT_COLOR = "#636e72"
SUB_ROW_FONT_SIZE = 10

DETAIL_ROW_HEIGHT = 30
DETAIL_ROW_BG = "#ffffff"
DETAIL_LABEL_FONT_COLOR = "#888888"
DETAIL_LABEL_FONT_SIZE = 9

BAR_LABEL_HEIGHT = 12
BAR_LABEL_OFFSET_Y = 1     # row_y + 1
BAR_HEIGHT = 14
BAR_OFFSET_Y = 13          # row_y + 13
BAR_ARC_SIZE = 40
BAR_MIN_WIDTH = 10

# ---- 월 경계 점선 ----
MONTH_DIVIDER_COLOR = "#95a5a6"
MONTH_DIVIDER_DASH_PATTERN = [8, 4]
MONTH_DIVIDER_WIDTH = 1.5

# ---- 파트 기본 색상 팔레트 (순환 배정, 사용자 변경 가능) ----
DEFAULT_PALETTE = [
    "#6C5CE7",
    "#E17055",
    "#0984E3",
    "#E84393",
    "#00B894",
    "#FDCB6E",
    "#A29BFE",
]

# ---- LLM 프로바이더 (WBS 파싱용) ----
# 사용자가 가진 키에 맞는 모델사를 골라 쓸 수 있도록 멀티 프로바이더 지원.
# id: settings.py에 저장되는 키, label: UI 표시명, model: 파싱에 사용할 모델,
# key_hint: 입력창 placeholder, vision: 이미지(Vision) 파싱 지원 여부.
LLM_MAX_TOKENS = 8000

PROVIDERS = {
    "anthropic": {
        "label": "Anthropic Claude",
        "model": "claude-sonnet-4-6",
        "key_hint": "sk-ant-...",
        "vision": True,
    },
    "openai": {
        "label": "OpenAI GPT",
        "model": "gpt-4o",
        "key_hint": "sk-...",
        "vision": True,
    },
    "google": {
        "label": "Google Gemini",
        "model": "gemini-2.0-flash",
        "key_hint": "AIza...",
        "vision": True,
    },
}
DEFAULT_PROVIDER = "anthropic"

SUPPORTED_EXCEL_EXT = (".xlsx", ".xls")
SUPPORTED_IMAGE_EXT = (".png", ".jpg", ".jpeg")
SUPPORTED_PDF_EXT = (".pdf",)
SUPPORTED_JSON_EXT = (".json",)
SUPPORTED_DRAWIO_EXT = (".drawio",)
