"""WBS 입력 파일(Excel/JSON/이미지/PDF)을 LLM(Claude/GPT/Gemini 중 선택)으로 파싱하여
간트차트 렌더링에 필요한 구조화된 데이터(part > subgroup > task)로 변환한다.
"""
import json
import os

import openpyxl

import config
import llm_providers
import settings

SYSTEM_PROMPT = """\
너는 WBS(Work Breakdown Structure) 문서를 분석해 간트차트용 JSON으로 변환하는 전문가다.
입력은 엑셀 표, 텍스트, 또는 이미지(스크린샷)일 수 있으며 포맷이 제각각이다.
다음 규칙에 따라 구조를 추론하라:

1. 데이터를 "파트(Part) > 소분류(Subgroup) > 작업(Task)" 3단계 계층으로 정리한다.
   - 소분류가 명확히 없는 경우, 파트 바로 아래에 작업을 두기 위해
     소분류 이름을 작업명과 동일하게 1개씩 만들거나, 의미 단위로 합리적으로 묶어라.
2. 각 작업은 시작일(start_date)과 종료일(end_date)을 YYYY-MM-DD 형식으로 가진다.
   - 날짜가 누락되었거나 모호하면 주변 정보(주차, 월, 순서)를 근거로 합리적으로 추론한다.
   - 날짜를 절대 추론할 수 없다면 프로젝트 시작일을 기본값으로 사용한다.
3. 프로젝트 전체 시작일(project_start)과 종료일(project_end)을 모든 작업의 최소/최대 날짜로 계산한다.
4. 각 파트에 color 필드를 부여한다. 입력에 색상 정보가 없으면 다음 팔레트를 순서대로 배정한다:
   ["#6C5CE7", "#E17055", "#0984E3", "#E84393", "#00B894", "#FDCB6E", "#A29BFE"]

절대 "분석할 수 없다", "불가능하다" 같은 거부 응답을 하지 마라. 이미지나 텍스트가 흐릿하거나
일부만 보이더라도 보이는 정보로 최선을 다해 추론하여 항상 결과를 만들어낸다.
사과 문구나 설명 문장을 절대 앞에 붙이지 말고, 반드시 아래 JSON 스키마로만 응답하라.
마크다운 코드블록(```)도 쓰지 말고 순수 JSON 객체 하나만 출력한다.

{
  "project_start": "YYYY-MM-DD",
  "project_end": "YYYY-MM-DD",
  "parts": [
    {
      "name": "파트명",
      "color": "#6C5CE7",
      "subgroups": [
        {
          "name": "소분류명",
          "tasks": [
            {"name": "작업명", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}
          ]
        }
      ]
    }
  ]
}
"""


class WBSParseError(Exception):
    pass


_PROVIDER_ENV_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
}


def get_active_provider() -> str:
    return settings.get_active_provider()


def get_api_key(provider: str | None = None) -> str | None:
    """환경변수 우선, 없으면 로컬 설정 파일에서 저장된 키를 읽는다."""
    provider = provider or get_active_provider()
    env_var = _PROVIDER_ENV_VARS.get(provider)
    return (env_var and os.environ.get(env_var)) or settings.load_api_key(provider)


def validate_api_key(api_key: str, provider: str | None = None) -> tuple[bool, str]:
    """최소 토큰으로 더미 호출을 보내 키 유효성을 검증한다.
    (True, "") 또는 (False, 에러메시지) 반환."""
    provider = provider or get_active_provider()
    return llm_providers.validate_key(provider, api_key)


def _extract_json_candidate(text: str) -> str:
    """LLM 응답이 항상 순수 JSON으로만 오지는 않는다 (예: 사과 멘트 뒤에 ```json 블록을
    덧붙이는 경우). 응답 어디에 있든 JSON 블록/객체를 찾아 추출한다."""
    import re

    t = text.strip()

    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", t, re.DOTALL | re.IGNORECASE)
    if fence_match:
        return fence_match.group(1)

    first = t.find("{")
    last = t.rfind("}")
    if first != -1 and last != -1 and last > first:
        return t[first : last + 1]

    return t


def _call_llm_text(content_text: str) -> dict:
    provider = get_active_provider()
    api_key = get_api_key(provider)
    if not api_key:
        raise WBSParseError(
            f"{config.PROVIDERS.get(provider, {}).get('label', provider)} API 키가 설정되지 않았습니다. "
            "앱에서 API 키를 입력해주세요."
        )
    raw = llm_providers.text_completion(provider, api_key, SYSTEM_PROMPT, content_text)
    return _parse_json_response(raw)


def _call_llm_vision(image_bytes: bytes, media_type: str) -> dict:
    provider = get_active_provider()
    if not config.PROVIDERS.get(provider, {}).get("vision"):
        raise WBSParseError(f"{provider} 프로바이더는 이미지(Vision) 파싱을 지원하지 않습니다.")
    api_key = get_api_key(provider)
    if not api_key:
        raise WBSParseError(
            f"{config.PROVIDERS.get(provider, {}).get('label', provider)} API 키가 설정되지 않았습니다. "
            "앱에서 API 키를 입력해주세요."
        )
    instruction = "이 이미지에 있는 WBS/일정표를 분석해서 지정된 JSON 스키마로 변환해줘."
    raw = llm_providers.vision_completion(provider, api_key, SYSTEM_PROMPT, image_bytes, media_type, instruction)
    return _parse_json_response(raw)


def _parse_json_response(raw: str) -> dict:
    try:
        return json.loads(_extract_json_candidate(raw))
    except json.JSONDecodeError as e:
        raise WBSParseError(
            f"LLM 응답을 JSON으로 해석할 수 없습니다: {e}\n"
            f"모델 응답: {raw[:500]}"
        )


# ---- 입력 포맷별 전처리 ----

def _excel_to_text(path: str) -> str:
    wb = openpyxl.load_workbook(path, data_only=True)
    lines = []
    for ws in wb.worksheets:
        lines.append(f"[시트: {ws.title}]")
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) if c is not None else "" for c in row]
            if any(cell.strip() for cell in cells):
                lines.append("\t".join(cells))
    return "\n".join(lines)


def _pdf_to_text(path: str) -> str:
    from pypdf import PdfReader

    reader = PdfReader(path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _json_to_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _image_media_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    return "image/png"


# ---- draw.io 입력 (LLM 호출 없이 좌표 기반으로 직접 복원) ----
#
# 우리 렌더러(renderer.py)가 만드는 draw.io와 동일한 레이아웃 규칙
# (라벨영역 너비, 1주 간격 px, 날짜 헤더가 매주 월요일)을 가진 drawio 파일이라면
# 셀의 x/y/width/height 좌표만으로 파트>소분류>작업 계층과 날짜를 그대로 복원할 수 있다.
# 날짜 헤더 2개 이상의 x좌표 간격으로 그리드 스케일을 그 파일 기준으로 스스로 추정하므로
# 우리 config 상수와 다른 px 스케일을 쓴 drawio라도 동작한다.

import datetime as _dt
import re as _re
import xml.etree.ElementTree as _ET

_DATE_HEADER_RE = _re.compile(r"^\d{1,2}/\d{1,2}$")


def _drawio_style_dict(style: str) -> dict:
    d = {}
    for part in (style or "").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            d[k] = v
    return d


def _drawio_base_color(fill: str) -> str:
    if fill and fill.startswith("#") and len(fill) > 7:
        return fill[:7]
    return fill or config.DEFAULT_PALETTE[0]


def _drawio_load_items(path: str) -> list:
    tree = _ET.parse(path)
    items = []
    for c in tree.getroot().findall(".//mxCell"):
        if c.get("vertex") != "1":
            continue
        geo = c.find("mxGeometry")
        if geo is None:
            continue
        st = _drawio_style_dict(c.get("style", ""))
        items.append(
            {
                "x": float(geo.get("x", 0)),
                "y": float(geo.get("y", 0)),
                "w": float(geo.get("width", 0)),
                "h": float(geo.get("height", 0)),
                "val": (c.get("value") or "").strip(),
                "fill": st.get("fillColor", ""),
            }
        )
    return items


def _drawio_calibrate(items: list):
    date_cells = sorted((it for it in items if _DATE_HEADER_RE.match(it["val"])), key=lambda i: i["x"])
    if len(date_cells) < 2:
        raise WBSParseError("draw.io 파일에서 날짜 헤더(예: 3/2, 3/9 ...)를 찾을 수 없습니다.")

    label_width = date_cells[0]["x"]
    week_width = date_cells[1]["x"] - date_cells[0]["x"]
    header_bottom = max(it["y"] + it["h"] for it in date_cells)
    month, day = map(int, date_cells[0]["val"].split("/"))

    now_year = _dt.date.today().year
    chosen_year = now_year
    for y in range(now_year - 1, now_year + 3):
        try:
            if _dt.date(y, month, day).weekday() == 0:  # 월요일
                chosen_year = y
                break
        except ValueError:
            continue

    grid_start = _dt.date(chosen_year, month, day)
    return label_width, week_width, grid_start, header_bottom


def _drawio_to_dict(path: str) -> dict:
    items = _drawio_load_items(path)
    label_width, week_width, grid_start, header_bottom = _drawio_calibrate(items)

    def x_to_date(x: float) -> _dt.date:
        days = (x - label_width) / week_width * 7
        return grid_start + _dt.timedelta(days=round(days))

    body_items = [it for it in items if it["y"] >= header_bottom - 1]

    label_rows = sorted(
        (
            it
            for it in body_items
            if 0 <= it["x"] <= label_width * 0.25 and it["w"] >= label_width * 0.5 and it["val"]
        ),
        key=lambda i: i["y"],
    )
    bars = [it for it in body_items if it["x"] >= label_width - 5 and 8 <= it["h"] <= 20]
    phase_rows = [
        it
        for it in items
        if it["y"] < 1 and it["x"] >= label_width - 1 and it["val"] and it["fill"] not in ("", "none")
    ]

    def find_bar(row: dict):
        for b in bars:
            if b["y"] >= row["y"] - 1 and b["y"] + b["h"] <= row["y"] + row["h"] + 1:
                return b
        return None

    parts: list = []
    cur_part = None
    cur_sub = None

    def ensure_part():
        nonlocal cur_part
        if cur_part is None:
            cur_part = {"name": "(미분류)", "color": config.DEFAULT_PALETTE[0], "subgroups": []}
            parts.append(cur_part)
        return cur_part

    def ensure_sub(default_name: str):
        nonlocal cur_sub
        if cur_sub is None:
            cur_sub = {"name": default_name, "tasks": []}
            ensure_part()["subgroups"].append(cur_sub)
        return cur_sub

    for row in label_rows:
        fill = (row["fill"] or "").lower()
        is_subgroup_bg = fill == "#f0f0f0"
        is_white_bg = fill in ("#ffffff", "#fff", "none", "")

        if 24 <= row["h"] < 28 and not is_subgroup_bg and not is_white_bg:
            cur_part = {"name": row["val"], "color": _drawio_base_color(row["fill"]), "subgroups": []}
            parts.append(cur_part)
            cur_sub = None
        elif 24 <= row["h"] < 28 and is_subgroup_bg:
            cur_sub = {"name": row["val"], "tasks": []}
            ensure_part()["subgroups"].append(cur_sub)
        elif row["h"] >= 28:
            bar = find_bar(row)
            if bar:
                start_date, end_date = x_to_date(bar["x"]), x_to_date(bar["x"] + bar["w"])
            else:
                start_date = end_date = grid_start
            sub = ensure_sub(row["val"])
            sub["tasks"].append(
                {"name": row["val"], "start_date": start_date.isoformat(), "end_date": end_date.isoformat()}
            )

    all_dates = [t["start_date"] for p in parts for sg in p["subgroups"] for t in sg["tasks"]]
    all_dates += [t["end_date"] for p in parts for sg in p["subgroups"] for t in sg["tasks"]]
    if not all_dates:
        raise WBSParseError("draw.io 파일에서 작업(task) 막대를 찾지 못했습니다.")

    phases = [
        {
            "name": p["val"],
            "color": _drawio_base_color(p["fill"]),
            "start_date": x_to_date(p["x"]).isoformat(),
            "end_date": x_to_date(p["x"] + p["w"]).isoformat(),
        }
        for p in sorted(phase_rows, key=lambda i: i["x"])
    ]

    return {
        "project_start": min(all_dates),
        "project_end": max(all_dates),
        "parts": parts,
        "phases": phases,
    }


def parse_wbs_file(path: str) -> dict:
    """입력 파일 경로를 받아 WBS 구조 dict를 반환한다.
    draw.io는 좌표 기반으로 LLM 호출 없이 직접 복원하고,
    그 외 포맷(Excel/JSON/PDF/이미지)은 선택된 LLM 프로바이더로 파싱한다."""
    ext = os.path.splitext(path)[1].lower()

    if ext in config.SUPPORTED_DRAWIO_EXT:
        result = _drawio_to_dict(path)
    elif ext in config.SUPPORTED_IMAGE_EXT:
        with open(path, "rb") as f:
            image_bytes = f.read()
        result = _call_llm_vision(image_bytes, _image_media_type(path))
    elif ext in config.SUPPORTED_EXCEL_EXT:
        text = _excel_to_text(path)
        result = _call_llm_text(text)
    elif ext in config.SUPPORTED_PDF_EXT:
        text = _pdf_to_text(path)
        result = _call_llm_text(text)
    elif ext in config.SUPPORTED_JSON_EXT:
        text = _json_to_text(path)
        result = _call_llm_text(text)
    else:
        raise WBSParseError(f"지원하지 않는 파일 형식입니다: {ext}")

    _assign_missing_colors(result)
    _sanitize_dates(result)
    return result


def _assign_missing_colors(result: dict) -> None:
    palette = config.DEFAULT_PALETTE
    idx = 0
    for part in result.get("parts", []):
        if not part.get("color"):
            part["color"] = palette[idx % len(palette)]
        idx += 1


def _fix_date_str(value: str, fallback: str) -> str:
    """LLM(특히 Vision)이 가끔 '2026-02-30'처럼 존재하지 않는 날짜를 반환하는 경우,
    해당 월의 마지막 유효한 날로 보정한다. 형식 자체가 깨졌으면 fallback을 사용한다."""
    import calendar
    import re

    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", str(value).strip())
    if not m:
        return fallback
    year, month, day = (int(g) for g in m.groups())
    if not (1 <= month <= 12):
        return fallback
    last_day = calendar.monthrange(year, month)[1]
    day = min(max(day, 1), last_day)
    return f"{year:04d}-{month:02d}-{day:02d}"


def _sanitize_dates(result: dict) -> None:
    fallback = result.get("project_start") or "2026-01-01"
    for part in result.get("parts", []):
        for sg in part.get("subgroups", []):
            for task in sg.get("tasks", []):
                task["start_date"] = _fix_date_str(task.get("start_date"), fallback)
                task["end_date"] = _fix_date_str(task.get("end_date"), task["start_date"])
                if task["end_date"] < task["start_date"]:
                    task["end_date"] = task["start_date"]
    for phase in result.get("phases", []):
        phase["start_date"] = _fix_date_str(phase.get("start_date"), fallback)
        phase["end_date"] = _fix_date_str(phase.get("end_date"), phase["start_date"])

    all_dates = [
        d
        for part in result.get("parts", [])
        for sg in part.get("subgroups", [])
        for task in sg.get("tasks", [])
        for d in (task["start_date"], task["end_date"])
    ]
    if all_dates:
        result["project_start"] = min(all_dates)
        result["project_end"] = max(all_dates)
