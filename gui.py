"""PyQt6 기반 WBS 간트차트 미리보기/수정 UI."""
from __future__ import annotations

import datetime as dt
import io
import os

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QKeyEvent, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

import config
import exporter
import parser as wbs_parser
import renderer
import settings
from renderer import Part, Subgroup, Task, WBSData

# 테이블 행 종류
ROW_PART = "part"
ROW_SUBGROUP = "subgroup"
ROW_TASK = "task"

COL_NAME = 0
COL_START = 1
COL_END = 2
COL_COLOR = 3


class ParseWorker(QThread):
    finished_ok = pyqtSignal(dict)
    finished_err = pyqtSignal(str)

    def __init__(self, path: str):
        super().__init__()
        self.path = path

    def run(self):
        try:
            result = wbs_parser.parse_wbs_file(self.path)
            self.finished_ok.emit(result)
        except Exception as e:  # noqa: BLE001
            self.finished_err.emit(str(e))


class ApiKeyValidateWorker(QThread):
    finished_result = pyqtSignal(bool, str)

    def __init__(self, provider: str, api_key: str):
        super().__init__()
        self.provider = provider
        self.api_key = api_key

    def run(self):
        ok, msg = wbs_parser.validate_api_key(self.api_key, self.provider)
        self.finished_result.emit(ok, msg)


class ApiKeyDialog(QDialog):
    """LLM 프로바이더 선택 + API 키 입력/검증 다이얼로그.
    유효한 키가 저장될 때까지 닫히지 않는다."""

    def __init__(self, parent=None, allow_cancel: bool = True):
        super().__init__(parent)
        self.setWindowTitle("API 키 설정")
        self.setMinimumWidth(440)
        self._worker: ApiKeyValidateWorker | None = None
        self.allow_cancel = allow_cancel

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "WBS 분석에 사용할 LLM 모델사를 선택하고 해당 API 키를 입력하세요.\n"
            "키는 이 PC의 사용자 설정 파일에만 저장됩니다.\n"
            f"저장 위치: {settings.get_config_path_str()}"
        ))

        self.provider_combo = QComboBox()
        for pid, info in config.PROVIDERS.items():
            self.provider_combo.addItem(info["label"], pid)
        active = settings.get_active_provider()
        idx = self.provider_combo.findData(active)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        layout.addWidget(self.provider_combo)

        self.input = QLineEdit()
        self.input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.input)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #888;")
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox.StandardButton.Ok
        if allow_cancel:
            buttons |= QDialogButtonBox.StandardButton.Cancel
        self.button_box = QDialogButtonBox(buttons)
        self.button_box.accepted.connect(self.on_confirm)
        if allow_cancel:
            self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self._on_provider_changed()

    def _current_provider(self) -> str:
        return self.provider_combo.currentData()

    def _on_provider_changed(self):
        provider = self._current_provider()
        info = config.PROVIDERS[provider]
        self.input.setPlaceholderText(info["key_hint"])
        existing = wbs_parser.get_api_key(provider)
        self.input.setText(existing or "")
        self.status_label.setText("")

    def on_confirm(self):
        provider = self._current_provider()
        key = self.input.text().strip()
        if not key:
            self.status_label.setText("키를 입력해주세요.")
            return

        self.status_label.setText("키 검증 중...")
        self.button_box.setEnabled(False)
        self.provider_combo.setEnabled(False)
        self._worker = ApiKeyValidateWorker(provider, key)
        self._worker.finished_result.connect(lambda ok, msg: self._on_validated(ok, msg, provider, key))
        self._worker.start()

    def _on_validated(self, ok: bool, msg: str, provider: str, key: str):
        self.button_box.setEnabled(True)
        self.provider_combo.setEnabled(True)
        if ok:
            settings.save_api_key(provider, key)
            self.status_label.setText("검증 완료")
            self.accept()
        else:
            self.status_label.setText(msg)


class PartColorDialog(QDialog):
    """기본 팔레트를 스와치로 보여주고 클릭 한 번에 고르거나,
    '직접 선택...'으로 전체 색상 선택창을 띄우는 다이얼로그."""

    SWATCH_SIZE = 36

    def __init__(self, current_color: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("파트 색상 선택")
        self.selected_color: str | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("기본 팔레트에서 선택:"))

        swatch_row = QHBoxLayout()
        for color in config.DEFAULT_PALETTE:
            btn = QPushButton()
            btn.setFixedSize(self.SWATCH_SIZE, self.SWATCH_SIZE)
            border = "2px solid #2d3436" if color.lower() == current_color.lower() else "1px solid #ccc"
            btn.setStyleSheet(f"background-color: {color}; border: {border}; border-radius: 4px;")
            btn.setToolTip(color)
            btn.clicked.connect(lambda _checked, c=color: self._choose(c))
            swatch_row.addWidget(btn)
        layout.addLayout(swatch_row)

        custom_btn = QPushButton("직접 선택...")
        custom_btn.clicked.connect(self._choose_custom)
        layout.addWidget(custom_btn)

        cancel_btn = QPushButton("취소")
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)

    def _choose(self, color: str):
        self.selected_color = color
        self.accept()

    def _choose_custom(self):
        color = QColorDialog.getColor(QColor(), self, "사용자 지정 색상")
        if color.isValid():
            self.selected_color = color.name()
            self.accept()


class WBSTableWidget(QTableWidget):
    """Enter로 다음 셀로 넘어갈 때 작업 행을 자동 추가하고, Delete 키로 행을 삭제할 수 있게
    한 QTableWidget. 실제 데이터 변경은 MainWindow가 신호를 받아 처리한다
    (스프레드시트/Notion에서 흔한 'Enter=새 항목, Delete=삭제' 패턴)."""

    enter_on_row = pyqtSignal(int)
    delete_on_row = pyqtSignal(int)

    def closeEditor(self, editor, hint):
        from PyQt6.QtWidgets import QAbstractItemDelegate

        row = self.currentIndex().row()
        is_enter = hint == QAbstractItemDelegate.EndEditHint.EditNextItem
        super().closeEditor(editor, hint)
        if is_enter and row >= 0:
            self.enter_on_row.emit(row)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Delete and self.state() != QTableWidget.State.EditingState:
            row = self.currentRow()
            if row >= 0:
                self.delete_on_row.emit(row)
                event.accept()
                return
        super().keyPressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WBS → 간트차트 생성기")
        self.resize(1400, 800)

        self.data: WBSData | None = None
        self.worker: ParseWorker | None = None

        self._build_ui()

    # ---- UI 구성 ----

    def _build_ui(self):
        toolbar = QToolBar()
        self.addToolBar(toolbar)

        open_btn = QPushButton("파일 열기 (Excel/JSON/이미지/PDF)")
        open_btn.clicked.connect(self.on_open_file)
        toolbar.addWidget(open_btn)

        refresh_btn = QPushButton("미리보기 갱신")
        refresh_btn.clicked.connect(self.on_refresh_preview)
        toolbar.addWidget(refresh_btn)

        export_btn = QPushButton("PNG로 내보내기")
        export_btn.clicked.connect(self.on_export_png)
        toolbar.addWidget(export_btn)

        export_json_btn = QPushButton("JSON으로 내보내기")
        export_json_btn.clicked.connect(self.on_export_json)
        toolbar.addWidget(export_json_btn)

        export_excel_btn = QPushButton("Excel로 내보내기")
        export_excel_btn.clicked.connect(self.on_export_excel)
        toolbar.addWidget(export_excel_btn)

        export_drawio_btn = QPushButton("draw.io로 내보내기")
        export_drawio_btn.clicked.connect(self.on_export_drawio)
        toolbar.addWidget(export_drawio_btn)

        api_key_btn = QPushButton("API 키 변경")
        api_key_btn.clicked.connect(self.on_change_api_key)
        toolbar.addWidget(api_key_btn)

        central = QWidget()
        layout = QHBoxLayout(central)

        # 좌측: 편집 테이블
        left = QVBoxLayout()
        left.addWidget(QLabel(
            "파트 / 소분류 / 작업 (더블클릭 수정, 색상은 더블클릭 / "
            "작업 행에서 Enter=아래에 새 작업 추가, Delete=행 삭제, 우클릭=메뉴)"
        ))
        self.table = WBSTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["이름", "시작일(YYYY-MM-DD)", "종료일(YYYY-MM-DD)", "색상"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(self.on_table_double_clicked)
        self.table.enter_on_row.connect(self.on_enter_on_row)
        self.table.delete_on_row.connect(self.on_delete_row)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.on_table_context_menu)
        left.addWidget(self.table)

        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setMinimumWidth(560)

        # 우측: 미리보기
        self.preview_label = QLabel("파일을 열어 WBS를 파싱하세요.")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll = QScrollArea()
        scroll.setWidget(self.preview_label)
        scroll.setWidgetResizable(True)

        layout.addWidget(left_widget, 2)
        layout.addWidget(scroll, 3)

        self.setCentralWidget(central)
        self.statusBar().showMessage("준비됨")

    # ---- 파일 열기 / 파싱 ----

    def on_change_api_key(self):
        dialog = ApiKeyDialog(self, allow_cancel=True)
        if dialog.exec():
            self.statusBar().showMessage("API 키가 저장되었습니다.")

    def on_open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "WBS 파일 선택",
            "",
            "WBS 파일 (*.xlsx *.xls *.json *.png *.jpg *.jpeg *.pdf *.drawio)",
        )
        if not path:
            return

        ext = os.path.splitext(path)[1].lower()
        if ext in config.SUPPORTED_IMAGE_EXT:
            proceed = QMessageBox.question(
                self,
                "이미지 입력 정확도 안내",
                "이미지는 LLM Vision으로 인식합니다.\n"
                "행이 많고 글씨가 작은 고밀도 차트는 정확히 읽지 못하고\n"
                "내용을 잘못 지어낼 수 있습니다 (환각).\n\n"
                "같은 자료의 Excel/JSON/draw.io 원본이 있다면 그쪽이 훨씬 정확합니다.\n"
                "그래도 이미지로 계속할까요?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if proceed != QMessageBox.StandardButton.Yes:
                return

        self.statusBar().showMessage(f"파싱 중... ({path})")
        self.worker = ParseWorker(path)
        self.worker.finished_ok.connect(self.on_parse_success)
        self.worker.finished_err.connect(self.on_parse_error)
        self.worker.start()

    def on_parse_success(self, result: dict):
        try:
            self.data = renderer.from_dict(result)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "파싱 오류", f"파싱 결과 변환 실패: {e}")
            self.statusBar().showMessage("파싱 실패")
            return
        self.statusBar().showMessage("파싱 완료. 표를 확인하고 수정하세요.")
        self._populate_table()
        self.on_refresh_preview()

    def on_parse_error(self, msg: str):
        QMessageBox.critical(self, "파싱 오류", msg)
        self.statusBar().showMessage("파싱 실패")

    # ---- 테이블 채우기 ----

    def _populate_table(self):
        self.table.setRowCount(0)
        if not self.data:
            return

        for part in self.data.parts:
            self._add_row(ROW_PART, part.name, "", "", part.color, ref=part, parent=None)
            for sg in part.subgroups:
                self._add_row(ROW_SUBGROUP, sg.name, "", "", "", ref=sg, parent=part)
                for task in sg.tasks:
                    self._add_row(
                        ROW_TASK,
                        task.name,
                        task.start_date.isoformat(),
                        task.end_date.isoformat(),
                        "",
                        ref=task,
                        parent=sg,
                    )

    def _add_row(self, kind: str, name: str, start: str, end: str, color: str, ref, parent):
        row = self.table.rowCount()
        self.table.insertRow(row)

        name_item = QTableWidgetItem(name)
        name_item.setData(Qt.ItemDataRole.UserRole, (kind, ref, parent))
        self.table.setItem(row, COL_NAME, name_item)
        self.table.setItem(row, COL_START, QTableWidgetItem(start))
        self.table.setItem(row, COL_END, QTableWidgetItem(end))

        color_item = QTableWidgetItem(color)
        if color:
            color_item.setBackground(QColor(color))
        self.table.setItem(row, COL_COLOR, color_item)

        if kind == ROW_PART:
            for col in range(4):
                item = self.table.item(row, col)
                if item:
                    item.setBackground(QColor("#dfe6e9"))
        elif kind == ROW_SUBGROUP:
            for col in range(3):
                item = self.table.item(row, col)
                if item:
                    item.setBackground(QColor("#f0f0f0"))

    def _row_info(self, row: int):
        item = self.table.item(row, COL_NAME)
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def on_table_double_clicked(self, row: int, col: int):
        info = self._row_info(row)
        if not info:
            return
        kind, ref, _parent = info
        if kind == ROW_PART and col == COL_COLOR:
            dialog = PartColorDialog(ref.color, self)
            if dialog.exec() and dialog.selected_color:
                ref.color = dialog.selected_color
                self.table.item(row, COL_COLOR).setText(ref.color)
                self.table.item(row, COL_COLOR).setBackground(QColor(ref.color))
                self.on_refresh_preview()

    def _sync_table_to_data(self):
        """테이블 셀의 텍스트 변경사항을 self.data 객체에 반영."""
        for row in range(self.table.rowCount()):
            info = self._row_info(row)
            if not info:
                continue
            kind, ref, _parent = info
            ref.name = self.table.item(row, COL_NAME).text()
            if kind == ROW_TASK:
                try:
                    ref.start_date = dt.datetime.strptime(
                        self.table.item(row, COL_START).text().strip(), "%Y-%m-%d"
                    ).date()
                    ref.end_date = dt.datetime.strptime(
                        self.table.item(row, COL_END).text().strip(), "%Y-%m-%d"
                    ).date()
                except ValueError:
                    pass

    # ---- 행 추가/삭제 (Enter=작업 추가, Delete=삭제, 우클릭=메뉴) ----

    def _next_palette_color(self) -> str:
        used = {p.color for p in (self.data.parts if self.data else [])}
        for c in config.DEFAULT_PALETTE:
            if c not in used:
                return c
        return config.DEFAULT_PALETTE[len(self.data.parts) % len(config.DEFAULT_PALETTE)]

    def _focus_and_rename(self, ref):
        """구조 변경 후 테이블을 다시 그리고, 새로 생긴 행의 이름 셀을 바로 편집 상태로 만든다
        (Notion 등에서 새 항목을 만들면 곧바로 이름을 입력할 수 있게 하는 것과 같은 패턴)."""
        self._populate_table()
        for row in range(self.table.rowCount()):
            info = self._row_info(row)
            if info and info[1] is ref:
                self.table.setCurrentCell(row, COL_NAME)
                self.table.editItem(self.table.item(row, COL_NAME))
                break

    def on_enter_on_row(self, row: int):
        """작업 행에서 Enter -> 바로 아래에 새 작업 행을 추가한다."""
        if not self.data:
            return
        info = self._row_info(row)
        if not info:
            return
        kind, ref, parent = info
        if kind != ROW_TASK:
            return
        self._sync_table_to_data()
        new_task = Task(name="새 작업", start_date=ref.start_date, end_date=ref.end_date)
        parent.tasks.insert(parent.tasks.index(ref) + 1, new_task)
        self._focus_and_rename(new_task)
        self.on_refresh_preview()

    def on_delete_row(self, row: int):
        info = self._row_info(row)
        if not info or not self.data:
            return
        kind, ref, parent = info
        self._confirm_and_delete(kind, ref, parent)

    def _confirm_and_delete(self, kind: str, ref, parent):
        if kind == ROW_TASK:
            msg = f"작업 '{ref.name}'을 삭제할까요?"
        elif kind == ROW_SUBGROUP:
            msg = f"소분류 '{ref.name}'과 하위 작업 {len(ref.tasks)}개를 모두 삭제할까요?"
        else:
            total_tasks = sum(len(sg.tasks) for sg in ref.subgroups)
            msg = f"파트 '{ref.name}'과 하위 소분류/작업({total_tasks}개)을 모두 삭제할까요?"

        if QMessageBox.question(
            self, "삭제 확인", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return

        self._sync_table_to_data()
        if kind == ROW_TASK:
            parent.tasks.remove(ref)
        elif kind == ROW_SUBGROUP:
            parent.subgroups.remove(ref)
        else:
            self.data.parts.remove(ref)
        self._populate_table()
        self.on_refresh_preview()

    def on_table_context_menu(self, pos):
        if not self.data:
            return
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        info = self._row_info(row)
        if not info:
            return
        kind, ref, parent = info

        menu = QMenu(self)
        if kind == ROW_TASK:
            act_add_above = menu.addAction("위에 작업 추가")
            act_add_below = menu.addAction("아래에 작업 추가")
            menu.addSeparator()
            act_add_sub = act_add_part = None
            act_delete = menu.addAction("이 작업 삭제")
        elif kind == ROW_SUBGROUP:
            act_add_sub = menu.addAction("이 소분류에 작업 추가")
            menu.addSeparator()
            act_add_above = menu.addAction("위에 소분류 추가")
            act_add_below = menu.addAction("아래에 소분류 추가")
            menu.addSeparator()
            act_add_part = None
            act_delete = menu.addAction("이 소분류 삭제 (하위 작업 포함)")
        else:
            act_add_part = menu.addAction("이 파트에 소분류 추가")
            menu.addSeparator()
            act_add_above = menu.addAction("위에 파트 추가")
            act_add_below = menu.addAction("아래에 파트 추가")
            menu.addSeparator()
            act_add_sub = None
            act_delete = menu.addAction("이 파트 삭제 (전체 하위 포함)")

        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        self._sync_table_to_data()

        if chosen is act_delete:
            self._confirm_and_delete(kind, ref, parent)
            return

        if kind == ROW_TASK:
            if chosen is act_add_above or chosen is act_add_below:
                new_task = Task(name="새 작업", start_date=ref.start_date, end_date=ref.end_date)
                idx = parent.tasks.index(ref) + (1 if chosen is act_add_below else 0)
                parent.tasks.insert(idx, new_task)
                self._focus_and_rename(new_task)
                self.on_refresh_preview()
        elif kind == ROW_SUBGROUP:
            if chosen is act_add_sub:
                new_task = Task(name="새 작업", start_date=self.data.project_start, end_date=self.data.project_start)
                ref.tasks.append(new_task)
                self._focus_and_rename(new_task)
                self.on_refresh_preview()
            elif chosen is act_add_above or chosen is act_add_below:
                new_sub = Subgroup(name="새 소분류", tasks=[])
                idx = parent.subgroups.index(ref) + (1 if chosen is act_add_below else 0)
                parent.subgroups.insert(idx, new_sub)
                self._focus_and_rename(new_sub)
                self.on_refresh_preview()
        else:  # ROW_PART
            if chosen is act_add_part:
                new_sub = Subgroup(name="새 소분류", tasks=[])
                ref.subgroups.append(new_sub)
                self._focus_and_rename(new_sub)
                self.on_refresh_preview()
            elif chosen is act_add_above or chosen is act_add_below:
                new_part = Part(name="새 파트", color=self._next_palette_color(), subgroups=[])
                idx = self.data.parts.index(ref) + (1 if chosen is act_add_below else 0)
                self.data.parts.insert(idx, new_part)
                self._focus_and_rename(new_part)
                self.on_refresh_preview()

    # ---- 미리보기 / 내보내기 ----

    def on_refresh_preview(self):
        if not self.data:
            return
        self._sync_table_to_data()
        try:
            img = renderer.render_to_image(self.data)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "렌더링 오류", str(e))
            return

        buf = io.BytesIO()
        img.save(buf, "PNG")
        pixmap = QPixmap()
        pixmap.loadFromData(buf.getvalue())
        self.preview_label.setPixmap(pixmap)
        self.preview_label.resize(pixmap.size())
        self.statusBar().showMessage("미리보기 갱신 완료")

    def on_export_png(self):
        if not self.data:
            QMessageBox.warning(self, "안내", "먼저 WBS 파일을 열어 파싱하세요.")
            return
        self._sync_table_to_data()

        path, _ = QFileDialog.getSaveFileName(self, "PNG로 저장", "gantt_chart.png", "PNG (*.png)")
        if not path:
            return
        try:
            renderer.render_to_png(self.data, path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "내보내기 오류", str(e))
            return
        self.statusBar().showMessage(f"저장 완료: {path}")
        QMessageBox.information(self, "완료", f"간트차트가 저장되었습니다:\n{path}")

    def on_export_json(self):
        self._export_with(
            "JSON으로 저장", "wbs_data.json", "JSON (*.json)", exporter.export_json
        )

    def on_export_excel(self):
        self._export_with(
            "Excel로 저장", "wbs_data.xlsx", "Excel (*.xlsx)", exporter.export_excel
        )

    def on_export_drawio(self):
        self._export_with(
            "draw.io로 저장", "gantt_chart.drawio", "draw.io (*.drawio)", exporter.export_drawio
        )

    def _export_with(self, dialog_title: str, default_name: str, file_filter: str, export_fn):
        if not self.data:
            QMessageBox.warning(self, "안내", "먼저 WBS 파일을 열어 파싱하세요.")
            return
        self._sync_table_to_data()

        path, _ = QFileDialog.getSaveFileName(self, dialog_title, default_name, file_filter)
        if not path:
            return
        try:
            export_fn(self.data, path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "내보내기 오류", str(e))
            return
        self.statusBar().showMessage(f"저장 완료: {path}")
        QMessageBox.information(self, "완료", f"파일이 저장되었습니다:\n{path}")


def run_app():
    app = QApplication.instance() or QApplication([])

    if not wbs_parser.get_api_key():
        dialog = ApiKeyDialog(allow_cancel=True)
        if not dialog.exec():
            return  # 사용자가 키 입력을 취소함 -> 앱 종료

    win = MainWindow()
    win.show()
    app.exec()
