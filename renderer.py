"""WBS 데이터(dict) -> 간트차트 PNG/PIL Image 렌더링."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont

import config


def parse_date(s: str) -> dt.date:
    if isinstance(s, dt.date):
        return s
    return dt.datetime.strptime(s, "%Y-%m-%d").date()


_FONT_CACHE: dict = {}


def _has_hangul(text: str) -> bool:
    return any("가" <= ch <= "힣" or "㄰" <= ch <= "㆏" for ch in text)


def _font_for(text: str, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """텍스트 내용에 한글이 있으면 맑은 고딕(글리프 지원), 없으면 Arial을 우선 사용한다.
    draw.io 기본 폰트는 Helvetica인데 Windows에는 해당 폰트 파일이 없어
    메트릭이 거의 동일한 Arial로 대체한다 (Helvetica는 macOS/웹 전용 폰트)."""
    korean = _has_hangul(text)
    key = (size, bold, korean)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]

    if korean:
        names = (
            ["malgunbd.ttf", "malgun.ttf", "NanumGothicBold.ttf", "NanumGothic.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"]
            if bold
            else ["malgun.ttf", "NanumGothic.ttf", "arial.ttf", "DejaVuSans.ttf"]
        )
    else:
        names = (
            ["arialbd.ttf", "Helvetica-Bold.ttf", "DejaVuSans-Bold.ttf"]
            if bold
            else ["arial.ttf", "Helvetica.ttf", "DejaVuSans.ttf"]
        )

    font = None
    for name in names:
        try:
            font = ImageFont.truetype(name, size)
            break
        except OSError:
            continue
    font = font or ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


@dataclass
class Task:
    name: str
    start_date: dt.date
    end_date: dt.date


@dataclass
class Subgroup:
    name: str
    tasks: list = field(default_factory=list)  # list[Task]


@dataclass
class Part:
    name: str
    color: str
    subgroups: list = field(default_factory=list)  # list[Subgroup]


@dataclass
class Phase:
    name: str
    start_date: dt.date
    end_date: dt.date
    color: str = "#dfe6e9"


@dataclass
class WBSData:
    project_start: dt.date
    project_end: dt.date
    parts: list  # list[Part]
    phases: list = field(default_factory=list)  # list[Phase]


def from_dict(d: dict) -> WBSData:
    parts = []
    for p in d.get("parts", []):
        subgroups = []
        for sg in p.get("subgroups", []):
            tasks = [
                Task(
                    name=t["name"],
                    start_date=parse_date(t["start_date"]),
                    end_date=parse_date(t["end_date"]),
                )
                for t in sg.get("tasks", [])
            ]
            subgroups.append(Subgroup(name=sg["name"], tasks=tasks))
        parts.append(Part(name=p["name"], color=p.get("color", "#6C5CE7"), subgroups=subgroups))

    phases = [
        Phase(
            name=ph["name"],
            start_date=parse_date(ph["start_date"]),
            end_date=parse_date(ph["end_date"]),
            color=ph.get("color", "#dfe6e9"),
        )
        for ph in d.get("phases", [])
    ]

    return WBSData(
        project_start=parse_date(d["project_start"]),
        project_end=parse_date(d["project_end"]),
        parts=parts,
        phases=phases,
    )


def to_dict(data: WBSData) -> dict:
    return {
        "project_start": data.project_start.isoformat(),
        "project_end": data.project_end.isoformat(),
        "parts": [
            {
                "name": p.name,
                "color": p.color,
                "subgroups": [
                    {
                        "name": sg.name,
                        "tasks": [
                            {
                                "name": t.name,
                                "start_date": t.start_date.isoformat(),
                                "end_date": t.end_date.isoformat(),
                            }
                            for t in sg.tasks
                        ],
                    }
                    for sg in p.subgroups
                ],
            }
            for p in data.parts
        ],
        "phases": [
            {
                "name": ph.name,
                "start_date": ph.start_date.isoformat(),
                "end_date": ph.end_date.isoformat(),
                "color": ph.color,
            }
            for ph in data.phases
        ],
    }


def _week_start(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())  # Monday


class GanttRenderer:
    """WBSData를 받아 레이아웃을 계산하고 PNG(PIL Image)로 렌더링한다."""

    def __init__(self, data: WBSData):
        self.data = data
        self.grid_start = _week_start(data.project_start)
        self.grid_end = data.project_end
        self.weeks = self._compute_weeks()
        self.content_width = config.LABEL_WIDTH + len(self.weeks) * config.WEEK_WIDTH
        self.content_height = self._compute_content_height()

    # ---- 좌표 계산 ----

    def date_to_x(self, d: dt.date) -> float:
        days_offset = (d - self.grid_start).days
        return config.LABEL_WIDTH + (days_offset / 7) * config.WEEK_WIDTH

    def _compute_weeks(self) -> list:
        weeks = []
        cur = self.grid_start
        while cur <= self.grid_end:
            weeks.append(cur)
            cur += dt.timedelta(days=7)
        if not weeks:
            weeks = [self.grid_start]
        return weeks

    def _compute_content_height(self) -> int:
        h = config.HEADER_TOTAL_HEIGHT
        for part in self.data.parts:
            h += config.PART_HEADER_HEIGHT
            for sg in part.subgroups:
                h += config.SUB_ROW_HEIGHT
                h += config.DETAIL_ROW_HEIGHT * len(sg.tasks)
        return h

    def _month_boundaries(self) -> list:
        """(month_label, first_monday_x) 리스트. 세로 점선/월헤더용."""
        result = []
        seen_months = set()
        for w in self.weeks:
            key = (w.year, w.month)
            if key not in seen_months:
                seen_months.add(key)
                result.append((f"{w.year}.{w.month:02d}", w))
        return result

    # ---- 렌더링 ----

    def render(self) -> Image.Image:
        width = self.content_width
        height = self.content_height
        img = Image.new("RGB", (width, height), config.BACKGROUND_COLOR)
        draw = ImageDraw.Draw(img)

        row_boundaries = self._row_boundaries()

        self._draw_grid(draw, width, height, row_boundaries)
        self._draw_body(draw)
        self._draw_phase_bar(draw, width)
        self._draw_month_header(draw, width)
        self._draw_date_header(draw)
        self._draw_month_dividers(draw, config.HEADER_TOTAL_HEIGHT, height)  # 최상위 z-order

        return img

    def _row_boundaries(self) -> list:
        """본문 영역(그리드 영역)의 각 행 y경계 목록. 그리드 가로선용."""
        ys = [config.HEADER_TOTAL_HEIGHT]
        y = config.HEADER_TOTAL_HEIGHT
        for part in self.data.parts:
            y += config.PART_HEADER_HEIGHT
            ys.append(y)
            for sg in part.subgroups:
                y += config.SUB_ROW_HEIGHT
                ys.append(y)
                for _ in sg.tasks:
                    y += config.DETAIL_ROW_HEIGHT
                    ys.append(y)
        return ys

    def _draw_grid(self, draw: ImageDraw.ImageDraw, width: int, height: int, row_boundaries: list):
        # 그리드 영역(날짜 영역)에만 주 단위 세로선 + 행 단위 가로선으로 셀 테두리 그리기
        grid_top = config.HEADER_TOTAL_HEIGHT
        for i in range(len(self.weeks) + 1):
            x = config.LABEL_WIDTH + i * config.WEEK_WIDTH
            draw.line([(x, grid_top), (x, height)], fill=config.GRID_BORDER_COLOR, width=1)
        for y in row_boundaries:
            draw.line([(config.LABEL_WIDTH, y), (width, y)], fill=config.GRID_BORDER_COLOR, width=1)

    def _draw_phase_bar(self, draw: ImageDraw.ImageDraw, width: int):
        if not self.data.phases:
            return
        for phase in self.data.phases:
            x1 = self.date_to_x(phase.start_date)
            x2 = self.date_to_x(phase.end_date)
            draw.rectangle([x1, 0, x2, config.PHASE_BAR_HEIGHT], fill=phase.color)
            text = phase.name
            font = _font_for(text, 11, bold=True)
            bbox = draw.textbbox((0, 0), text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            cx = (x1 + x2) / 2 - tw / 2
            cy = config.PHASE_BAR_HEIGHT / 2 - th / 2 - bbox[1]
            draw.text((cx, cy), text, fill="#2d3436", font=font)

    def _draw_month_header(self, draw: ImageDraw.ImageDraw, width: int):
        y0 = config.PHASE_BAR_HEIGHT
        y1 = y0 + config.MONTH_HEADER_HEIGHT
        draw.rectangle([0, y0, width, y1], fill=config.MONTH_HEADER_BG)

        boundaries = self._month_boundaries()
        for idx, (label, monday) in enumerate(boundaries):
            x_start = self.date_to_x(monday)
            x_end = self.date_to_x(boundaries[idx + 1][1]) if idx + 1 < len(boundaries) else width
            cx = (x_start + x_end) / 2
            font = _font_for(label, 11, bold=True)
            bbox = draw.textbbox((0, 0), label, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.text((cx - tw / 2, y0 + config.MONTH_HEADER_HEIGHT / 2 - th / 2 - bbox[1]), label, fill="#2d3436", font=font)

    def _draw_date_header(self, draw: ImageDraw.ImageDraw):
        y0 = config.DATE_HEADER_Y
        y1 = y0 + config.DATE_HEADER_HEIGHT
        for i, w in enumerate(self.weeks):
            x = config.LABEL_WIDTH + i * config.WEEK_WIDTH
            label = f"{w.month}/{w.day}"
            font = _font_for(label, 9)
            bbox = draw.textbbox((0, 0), label, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            cx = x + config.WEEK_WIDTH / 2 - tw / 2
            cy = y0 + config.DATE_HEADER_HEIGHT / 2 - th / 2 - bbox[1]
            draw.text((cx, cy), label, fill="#636e72", font=font)

    def _draw_body(self, draw: ImageDraw.ImageDraw) -> int:
        # draw.io 기본 텍스트 스타일(fontStyle=1=Bold)을 라벨 전반의 기본값으로 통일.
        # 색상은 행 종류별 기존 색을 그대로 유지하고, 폰트는 텍스트에 한글이 있는지에
        # 따라 맑은 고딕/Arial(Helvetica 대체)을 텍스트별로 자동 선택한다.
        y = config.HEADER_TOTAL_HEIGHT
        body_top = y

        label_w = config.LABEL_WIDTH

        for part in self.data.parts:
            part_top_y = y

            # 파트 헤더 행: 좌측 라벨 영역만 파트 컬러 배경 (그리드 영역은 비워둠)
            draw.rectangle([0, y, label_w, y + config.PART_HEADER_HEIGHT], fill=part.color)
            draw.text(
                (config.PART_COLORBAR_WIDTH + 10, y + config.PART_HEADER_HEIGHT / 2 - 7),
                part.name,
                fill="#ffffff",
                font=_font_for(part.name, 12, bold=True),
            )
            y += config.PART_HEADER_HEIGHT

            for sg in part.subgroups:
                # 소분류 행: 좌측 라벨 영역만 배경색 (그리드 영역은 비워둠)
                draw.rectangle([0, y, label_w, y + config.SUB_ROW_HEIGHT], fill=config.SUB_ROW_BG)
                draw.text(
                    (config.PART_COLORBAR_WIDTH + 18, y + config.SUB_ROW_HEIGHT / 2 - 6),
                    sg.name,
                    fill=config.SUB_ROW_FONT_COLOR,
                    font=_font_for(sg.name, config.SUB_ROW_FONT_SIZE, bold=True),
                )
                y += config.SUB_ROW_HEIGHT

                for task in sg.tasks:
                    # task 행: 좌측 라벨 영역 흰 배경 + 회색 텍스트, 그리드 영역엔 색상 바
                    draw.rectangle([0, y, label_w, y + config.DETAIL_ROW_HEIGHT], fill=config.DETAIL_ROW_BG)
                    draw.text(
                        (config.PART_COLORBAR_WIDTH + 26, y + config.DETAIL_ROW_HEIGHT / 2 - 6),
                        task.name,
                        fill=config.DETAIL_LABEL_FONT_COLOR,
                        font=_font_for(task.name, config.DETAIL_LABEL_FONT_SIZE, bold=True),
                    )
                    self._draw_task_bar(draw, task, y, part.color)
                    y += config.DETAIL_ROW_HEIGHT

            # 파트 좌측 세로 컬러바 (파트 시작~끝까지, 라벨 영역 맨 왼쪽)
            draw.rectangle([0, part_top_y, config.PART_COLORBAR_WIDTH, y], fill=part.color)

        return body_top

    def _draw_task_bar(self, draw: ImageDraw.ImageDraw, task: Task, row_y: int, color: str):
        x1 = self.date_to_x(task.start_date)
        days = (task.end_date - task.start_date).days
        width = max(config.BAR_MIN_WIDTH, (days / 7) * config.WEEK_WIDTH)
        x2 = x1 + width

        # 바 라벨 (바 시작 x, row_y+1)
        draw.text(
            (x1, row_y + config.BAR_LABEL_OFFSET_Y),
            task.name,
            fill=color,
            font=_font_for(task.name, 9, bold=True),
        )

        # 색상 바 (row_y+13, rounded)
        bar_top = row_y + config.BAR_OFFSET_Y
        bar_bottom = bar_top + config.BAR_HEIGHT
        radius = min(config.BAR_ARC_SIZE / 2, config.BAR_HEIGHT / 2)
        draw.rounded_rectangle([x1, bar_top, x2, bar_bottom], radius=radius, fill=color)

    def _draw_month_dividers(self, draw: ImageDraw.ImageDraw, top_y: int, bottom_y: int):
        boundaries = self._month_boundaries()
        for _, monday in boundaries:
            x = self.date_to_x(monday)
            self._draw_dashed_vline(draw, x, config.PHASE_BAR_HEIGHT, bottom_y)

    def _draw_dashed_vline(self, draw: ImageDraw.ImageDraw, x: float, y0: float, y1: float):
        dash_on, dash_off = config.MONTH_DIVIDER_DASH_PATTERN
        y = y0
        while y < y1:
            y_end = min(y + dash_on, y1)
            draw.line([(x, y), (x, y_end)], fill=config.MONTH_DIVIDER_COLOR, width=int(config.MONTH_DIVIDER_WIDTH))
            y = y_end + dash_off


    # ---- draw.io XML 내보내기 ----

    def to_drawio_xml(self) -> str:
        """draw.io(diagrams.net)에서 바로 열리는 mxGraphModel XML 문자열 생성.
        PNG와 동일한 레이아웃 좌표를 재사용해 셀(part/subgroup/task/bar)을
        편집 가능한 도형으로 내보낸다."""
        import xml.sax.saxutils as su

        cells = []
        next_id = [2]  # 0, 1은 root/layer 예약

        def new_id() -> str:
            next_id[0] += 1
            return str(next_id[0])

        def esc(s: str) -> str:
            return su.escape(str(s))

        def add_vertex(x, y, w, h, style, label=""):
            cid = new_id()
            cells.append(
                f'<mxCell id="{cid}" value="{esc(label)}" style="{style}" '
                f'vertex="1" parent="1">'
                f'<mxGeometry x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" as="geometry"/>'
                f'</mxCell>'
            )
            return cid

        def add_edge(x1, y1, x2, y2, style):
            cid = new_id()
            cells.append(
                f'<mxCell id="{cid}" style="{style}" edge="1" parent="1">'
                f'<mxGeometry relative="1" as="geometry">'
                f'<mxPoint x="{x1:.1f}" y="{y1:.1f}" as="sourcePoint"/>'
                f'<mxPoint x="{x2:.1f}" y="{y2:.1f}" as="targetPoint"/>'
                f'</mxGeometry></mxCell>'
            )
            return cid

        width = self.content_width
        height = self.content_height
        label_w = config.LABEL_WIDTH

        # 그리드 (세로 주 단위 + 가로 행 단위)
        row_boundaries = self._row_boundaries()
        grid_style = (
            f"endArrow=none;html=1;strokeColor={config.GRID_BORDER_COLOR};"
            f"strokeWidth=1;rounded=0;"
        )
        for i in range(len(self.weeks) + 1):
            x = config.LABEL_WIDTH + i * config.WEEK_WIDTH
            add_edge(x, config.HEADER_TOTAL_HEIGHT, x, height, grid_style)
        for y in row_boundaries:
            add_edge(label_w, y, width, y, grid_style)

        # 본문 (파트/소분류/task)
        y = config.HEADER_TOTAL_HEIGHT
        for part in self.data.parts:
            part_top_y = y

            add_vertex(
                0, y, label_w, config.PART_HEADER_HEIGHT,
                f"rounded=0;fillColor={part.color};strokeColor=none;fontColor=#ffffff;"
                f"fontStyle=1;align=left;spacingLeft={config.PART_COLORBAR_WIDTH + 10};",
                part.name,
            )
            y += config.PART_HEADER_HEIGHT

            for sg in part.subgroups:
                add_vertex(
                    0, y, label_w, config.SUB_ROW_HEIGHT,
                    f"rounded=0;fillColor={config.SUB_ROW_BG};strokeColor=none;"
                    f"fontColor={config.SUB_ROW_FONT_COLOR};fontStyle=1;align=left;"
                    f"spacingLeft={config.PART_COLORBAR_WIDTH + 18};",
                    sg.name,
                )
                y += config.SUB_ROW_HEIGHT

                for task in sg.tasks:
                    add_vertex(
                        0, y, label_w, config.DETAIL_ROW_HEIGHT,
                        f"rounded=0;fillColor={config.DETAIL_ROW_BG};strokeColor=none;"
                        f"fontColor={config.DETAIL_LABEL_FONT_COLOR};fontSize=9;fontStyle=1;align=left;"
                        f"spacingLeft={config.PART_COLORBAR_WIDTH + 26};",
                        task.name,
                    )

                    x1 = self.date_to_x(task.start_date)
                    days = (task.end_date - task.start_date).days
                    bar_w = max(config.BAR_MIN_WIDTH, (days / 7) * config.WEEK_WIDTH)
                    bar_top = y + config.BAR_OFFSET_Y

                    add_vertex(
                        x1, y + config.BAR_LABEL_OFFSET_Y, bar_w, config.BAR_LABEL_HEIGHT,
                        f"rounded=0;fillColor=none;strokeColor=none;fontColor={part.color};"
                        f"fontStyle=1;fontSize=9;align=left;",
                        task.name,
                    )
                    add_vertex(
                        x1, bar_top, bar_w, config.BAR_HEIGHT,
                        f"rounded=1;arcSize={config.BAR_ARC_SIZE};fillColor={part.color};strokeColor=none;",
                    )
                    y += config.DETAIL_ROW_HEIGHT

            add_vertex(0, part_top_y, config.PART_COLORBAR_WIDTH, y - part_top_y,
                       f"rounded=0;fillColor={part.color};strokeColor=none;")

        # Phase 바
        for phase in self.data.phases:
            x1 = self.date_to_x(phase.start_date)
            x2 = self.date_to_x(phase.end_date)
            add_vertex(
                x1, 0, x2 - x1, config.PHASE_BAR_HEIGHT,
                f"rounded=0;fillColor={phase.color};strokeColor=none;fontStyle=1;"
                f"fontColor=#2d3436;align=center;",
                phase.name,
            )

        # 월 헤더 / 날짜 헤더
        boundaries = self._month_boundaries()
        for idx, (label, monday) in enumerate(boundaries):
            x_start = self.date_to_x(monday)
            x_end = self.date_to_x(boundaries[idx + 1][1]) if idx + 1 < len(boundaries) else width
            add_vertex(
                x_start, config.PHASE_BAR_HEIGHT, x_end - x_start, config.MONTH_HEADER_HEIGHT,
                f"rounded=0;fillColor={config.MONTH_HEADER_BG};strokeColor=none;"
                f"fontStyle=1;fontColor=#2d3436;align=center;",
                label,
            )
        for i, w in enumerate(self.weeks):
            x = config.LABEL_WIDTH + i * config.WEEK_WIDTH
            add_vertex(
                x, config.DATE_HEADER_Y, config.WEEK_WIDTH, config.DATE_HEADER_HEIGHT,
                "rounded=0;fillColor=none;strokeColor=none;fontColor=#636e72;fontSize=9;align=center;",
                f"{w.month}/{w.day}",
            )

        # 월 경계 점선 (최상위 z-order: 마지막에 추가)
        for _, monday in boundaries:
            x = self.date_to_x(monday)
            add_edge(
                x, config.HEADER_TOTAL_HEIGHT, x, height,
                f"endArrow=none;html=1;dashed=1;dashPattern={' '.join(map(str, config.MONTH_DIVIDER_DASH_PATTERN))};"
                f"strokeColor={config.MONTH_DIVIDER_COLOR};strokeWidth={config.MONTH_DIVIDER_WIDTH};",
            )

        cells_xml = "".join(cells)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<mxfile host="app.diagrams.net">'
            '<diagram name="Gantt Chart">'
            '<mxGraphModel dx="800" dy="600" grid="0" gridSize="10" guides="1" tooltips="1" '
            'connect="1" arrows="1" fold="1" page="1" pageScale="1" '
            f'pageWidth="{int(width)}" pageHeight="{int(height)}" math="0" shadow="0">'
            '<root>'
            '<mxCell id="0"/>'
            '<mxCell id="1" parent="0"/>'
            f'{cells_xml}'
            '</root>'
            '</mxGraphModel>'
            '</diagram>'
            '</mxfile>'
        )


def render_to_png(data: WBSData, output_path: str) -> None:
    renderer = GanttRenderer(data)
    img = renderer.render()
    img.save(output_path, "PNG")


def render_to_image(data: WBSData) -> Image.Image:
    return GanttRenderer(data).render()
