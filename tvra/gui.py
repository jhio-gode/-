"""Chinese desktop interface; data stays on the local machine.

The module intentionally creates neither a database nor a QApplication on import.
Heavy writes and exports run in a background thread.  All widgets are updated
only by MainWindow's Qt slots on the application thread.
"""
from __future__ import annotations

import sys
import traceback
from dataclasses import asdict
from pathlib import Path

from PySide2.QtCore import QDate, Qt, QThread, Signal, Slot
from PySide2.QtGui import QColor, QFont
from PySide2.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDateEdit,
    QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QSpinBox, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem,
    QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from .domain import RuleConfig
from .reports import create_template, export_rankings, export_vehicle_report


APP_TITLE = "重点运输车辆异常轨迹智能研判系统"
LEVEL_COLORS = {0: "#62738a", 1: "#c53a46", 2: "#b3710d", 3: "#2877a5"}
LEVEL_NAMES = {0: "未发现规则线索", 1: "一级关注", 2: "二级关注", 3: "三级关注"}
EVENT_TYPES = {
    "E01": "同地点疑似短停", "E02": "高速脱离停返", "E03": "夜间异常组合",
    "E04": "风险地点疑似停留", "E05": "同企业多车关联", "E06": "区域高频往返",
}


STYLE = """
QWidget { font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
          font-size: 13px; color: #25344b; }
QMainWindow, QWidget#mainArea { background: #f3f6fa; }
QFrame#sidebar { background: #142944; border: none; }
QLabel#brand { color: #ffffff; font-size: 19px; font-weight: 700; }
QLabel#brandNote { color: #a4b7cf; font-size: 11px; }
QLabel#sidebarFooter { color: #9cb3ce; font-size: 11px; }
QListWidget#navigation { background: transparent; border: none; outline: none;
                       color: #b9c9dc; font-size: 14px; }
QListWidget#navigation::item { height: 47px; margin: 3px 10px; padding-left: 14px; border-radius: 7px; }
QListWidget#navigation::item:selected { background: #245188; color: white; }
QListWidget#navigation::item:hover:!selected { background: #203d5f; color: white; }
QLabel#pageTitle { font-size: 23px; color: #192f4d; font-weight: 700; }
QLabel#pageSubtitle { color: #708099; font-size: 12px; }
QLabel#sectionTitle { font-size: 15px; font-weight: 700; color: #203750; }
QLabel#muted { color: #748399; }
QLabel#empty { color: #76879d; padding: 14px; }
QFrame#card, QFrame#metric { background: white; border: 1px solid #e2e8f0; border-radius: 9px; }
QLabel#metricLabel { color: #76849a; font-size: 12px; }
QLabel#metricValue { font-size: 28px; color: #193b67; font-weight: 700; }
QLabel#metricNote { color: #8b98aa; font-size: 11px; }
QPushButton { background: white; border: 1px solid #d5deeb; border-radius: 5px;
              padding: 7px 13px; min-height: 19px; color: #334b68; }
QPushButton:hover { background: #edf4fd; border-color: #91afd2; }
QPushButton:pressed { background: #dfeaf8; }
QPushButton:disabled { color: #a5afbe; background: #f0f3f7; border-color: #e0e6ee; }
QPushButton#primary { background: #2665ab; color: white; border-color: #2665ab; font-weight: 600; }
QPushButton#primary:hover { background: #1d5392; }
QPushButton#primary:disabled { color: #dce5ef; background: #99b0cb; border-color: #99b0cb; }
QPushButton#danger { color: #b53f4a; }
QLineEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox { background: white;
    border: 1px solid #d6dfeb; border-radius: 5px; padding: 6px 8px; min-height: 20px; }
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #4b88c6; }
QComboBox::drop-down { border: none; width: 23px; }
QTableWidget { background: white; alternate-background-color: #f8fafd; border: 1px solid #e1e7ef;
               border-radius: 5px; gridline-color: #edf0f5; selection-background-color: #e5effc;
               selection-color: #213f65; outline: none; }
QTableWidget::item { padding: 7px 8px; border: none; }
QHeaderView::section { background: #f4f7fb; color: #62738b; border: none;
                      border-bottom: 1px solid #e1e7ef; padding: 9px 8px; font-weight: 600; }
QTableCornerButton::section { background: #f4f7fb; border: none; }
QTextEdit, QListWidget#files { background: white; border: 1px solid #e0e6ee; border-radius: 5px; padding: 7px; }
QTabWidget::pane { background: white; border: 1px solid #e1e7ef; border-radius: 5px; }
QTabBar::tab { background: #edf1f7; color: #677b94; padding: 9px 19px; margin-right: 3px; }
QTabBar::tab:selected { background: white; color: #2466aa; font-weight: 600; }
QGroupBox { font-weight: 600; border: 1px solid #dfe6ef; background: white;
            border-radius: 7px; margin-top: 12px; padding: 17px 12px 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 13px; padding: 0 4px; }
QScrollArea { border: none; background: transparent; }
QStatusBar { background: white; color: #708099; border-top: 1px solid #e1e7ef; }
QProgressBar { border: none; background: #e1e9f3; border-radius: 2px; max-height: 4px; }
QProgressBar::chunk { background: #3278bf; }
QToolTip { color: #25344b; background: #ffffff; border: 1px solid #c8d4e5; padding: 5px; }
"""


def _text(value):
    if value is None:
        return "—"
    if isinstance(value, (list, tuple, set)):
        return "、".join(str(item) for item in value) or "—"
    if isinstance(value, dict):
        return "；".join("{}：{}".format(key, val) for key, val in value.items()) or "—"
    return str(value) if value != "" else "—"


def _level(value):
    try:
        return LEVEL_NAMES.get(int(value or 0), str(value))
    except (ValueError, TypeError):
        return _text(value)


def _ratio(value):
    try:
        return "{:.1f}%".format(float(value) * 100)
    except (ValueError, TypeError):
        return "—"


def _vehicle_name(row):
    plate_type = row.get("plate_type", "")
    return "{}（{}）".format(row.get("plate", ""), plate_type) if plate_type else row.get("plate", "")


def _vehicle_key(row):
    return row.get("vehicle_key") or row.get("plate", "")


def _file_suffix(path, suffix):
    return path if path.lower().endswith(suffix) else path + suffix


def _resource_path(relative):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative


def _button(label, handler=None, primary=False):
    button = QPushButton(label)
    if primary:
        button.setObjectName("primary")
    if handler is not None:
        button.clicked.connect(handler)
    return button


def _label(text="", name=None, wrap=False):
    label = QLabel(text)
    if name:
        label.setObjectName(name)
    label.setWordWrap(wrap)
    label.setTextFormat(Qt.PlainText)
    return label


def _table(headers):
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setShowGrid(False)
    table.verticalHeader().hide()
    table.verticalHeader().setDefaultSectionSize(37)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
    table.horizontalHeader().setMinimumSectionSize(65)
    table.setSortingEnabled(True)
    table.setMinimumHeight(100)
    return table


def _populate(table, rows, columns, level_column=None):
    table.setSortingEnabled(False)
    table.setUpdatesEnabled(False)
    table.setRowCount(len(rows))
    for row_number, row in enumerate(rows):
        for column_number, get_value in enumerate(columns):
            value = get_value(row) if callable(get_value) else row.get(get_value)
            item = QTableWidgetItem()
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                item.setData(Qt.DisplayRole, value)
            else:
                item.setText(_text(value))
            item.setData(Qt.UserRole, row)
            item.setToolTip(_text(value))
            if column_number == level_column:
                try:
                    color = LEVEL_COLORS.get(int(row.get("level", row.get("risk_level", 0)) or 0), "#62738a")
                except (ValueError, TypeError):
                    color = "#62738a"
                item.setForeground(QColor(color))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            table.setItem(row_number, column_number, item)
    table.setUpdatesEnabled(True)
    table.setSortingEnabled(True)


def _selected(table):
    item = table.item(table.currentRow(), 0)
    return item.data(Qt.UserRole) if item is not None else None


class TaskThread(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, task, parent=None):
        super().__init__(parent)
        self.task = task

    def run(self):
        try:
            self.completed.emit(self.task())
        except Exception:
            self.failed.emit(traceback.format_exc())


class MetricCard(QFrame):
    def __init__(self, title, note="", parent=None):
        super().__init__(parent)
        self.setObjectName("metric")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)
        layout.addWidget(_label(title, "metricLabel"))
        self.value = _label("0", "metricValue")
        layout.addWidget(self.value)
        if note:
            layout.addWidget(_label(note, "metricNote", True))

    def set_value(self, value, color=None):
        self.value.setText(_text(value))
        self.value.setStyleSheet("color: {};".format(color) if color else "")


class MainWindow(QMainWindow):
    """The full desktop workflow, backed by the injected local Service."""

    PAGE_NAMES = ["研判概览", "数据导入", "风险事件", "车辆详情", "报告导出", "规则设置"]
    PAGE_DESCRIPTIONS = [
        "从过车数据中识别可追溯的异常线索，点击车辆查看研判依据。",
        "支持多车 XLSX / CSV 文件；校验、去重后保存至本机数据库。",
        "按时间、等级与事件类型筛选线索，并检查触发依据和数据限制。",
        "把车辆画像、过车记录、事件证据与分析历史放在一起核查。",
        "导出车辆排名 Excel 或单车 Word 研判报告，便于线下复核。",
        "调整可解释规则的阈值，保存后重新计算全部已导入数据。",
    ]

    def __init__(self, service):
        super().__init__()
        self.service = service
        self._job = None
        self._job_callback = None
        self._job_name = ""
        self._action_buttons = []
        self._vehicles = []
        self._events = []
        self._report_vehicles = []
        self._detail = None
        self._settings_widgets = {}
        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(980, 660)
        self.resize(1220, 820)
        self.setStyleSheet(STYLE)
        self._build_shell()
        self._build_dashboard()
        self._build_import()
        self._build_events()
        self._build_vehicle()
        self._build_reports()
        self._build_settings()
        self.navigation.setCurrentRow(0)
        self._refresh_all()

    def _build_shell(self):
        central = QWidget()
        shell = QHBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(183)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 25, 0, 17)
        brand = _label("重点运输车辆\n异常轨迹研判", "brand")
        brand.setContentsMargins(21, 0, 9, 0)
        side.addWidget(brand)
        brand_note = _label("TRANSPORT RISK ANALYSIS", "brandNote")
        brand_note.setContentsMargins(21, 9, 0, 22)
        side.addWidget(brand_note)
        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        self.navigation.setFocusPolicy(Qt.NoFocus)
        for index, title in enumerate(self.PAGE_NAMES):
            self.navigation.addItem("{:02d}   {}".format(index + 1, title))
        self.navigation.currentRowChanged.connect(self._change_page)
        side.addWidget(self.navigation, 1)
        foot = _label("本地运行 · 数据不上传\n规则线索 · 人工核查", "sidebarFooter")
        foot.setContentsMargins(21, 0, 0, 0)
        side.addWidget(foot)
        shell.addWidget(sidebar)
        main = QWidget()
        main.setObjectName("mainArea")
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(23, 21, 23, 17)
        main_layout.setSpacing(13)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(5)
        self.page_title = _label("", "pageTitle")
        self.page_subtitle = _label("", "pageSubtitle", True)
        titles.addWidget(self.page_title)
        titles.addWidget(self.page_subtitle)
        header.addLayout(titles, 1)
        refresh = _button("刷新", self._refresh_all)
        refresh.setToolTip("重新读取本机数据库")
        self._action_buttons.append(refresh)
        header.addWidget(refresh, 0, Qt.AlignTop)
        main_layout.addLayout(header)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        main_layout.addWidget(self.progress)
        self.pages = QStackedWidget()
        main_layout.addWidget(self.pages, 1)
        shell.addWidget(main, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage("就绪 · 所有数据均保存在本机")

    def _new_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.pages.addWidget(page)
        return layout

    def _managed_button(self, text, handler, primary=False):
        button = _button(text, handler, primary)
        self._action_buttons.append(button)
        return button

    def _build_dashboard(self):
        layout = self._new_page()
        cards = QHBoxLayout()
        self.dashboard_metrics = {}
        for key, title, note in [
            ("vehicles", "车辆总数", "按车牌汇总"),
            ("records", "有效过车记录", "重复记录不再入库"),
            ("events", "待核查风险事件", "规则触发的辅助线索"),
            ("level1", "一级事件", "优先核查"),
        ]:
            card = MetricCard(title, note)
            self.dashboard_metrics[key] = card
            cards.addWidget(card, 1)
        layout.addLayout(cards)
        controls = QHBoxLayout()
        self.coverage_label = _label("尚未导入数据", "muted", True)
        controls.addWidget(self.coverage_label, 1)
        controls.addWidget(_button("导入数据", lambda: self.navigation.setCurrentRow(1), True))
        controls.addWidget(self._managed_button("载入演示数据", self._import_demo))
        layout.addLayout(controls)
        self.dashboard_empty = _label(
            "数据库还是空的。先下载导入模板并填入过车记录，或载入合成演示数据体验完整流程。", "empty", True)
        self.dashboard_empty.setStyleSheet("background: #eaf2fc; border-radius: 7px; color: #3e6797;")
        layout.addWidget(self.dashboard_empty)
        splitter = QSplitter(Qt.Horizontal)
        distribution = QWidget()
        distribution_layout = QVBoxLayout(distribution)
        distribution_layout.setContentsMargins(0, 0, 5, 0)
        distribution_layout.addWidget(_label("事件类型分布", "sectionTitle"))
        self.event_distribution = _table(["事件类型", "数量"])
        distribution_layout.addWidget(self.event_distribution, 1)
        splitter.addWidget(distribution)
        priorities = QWidget()
        priorities_layout = QVBoxLayout(priorities)
        priorities_layout.setContentsMargins(5, 0, 0, 0)
        priorities_layout.addWidget(_label("关注车辆 · 双击查看详情", "sectionTitle"))
        self.priority_table = _table(["关注等级", "车牌号", "事件数", "最近过车"])
        self.priority_table.cellDoubleClicked.connect(lambda *_: self._open_table_vehicle(self.priority_table))
        priorities_layout.addWidget(self.priority_table, 1)
        splitter.addWidget(priorities)
        splitter.setSizes([310, 570])
        layout.addWidget(splitter, 1)
        self.dashboard_foot = _label("", "muted", True)
        layout.addWidget(self.dashboard_foot)

    def _build_import(self):
        layout = self._new_page()
        top = QHBoxLayout()
        top.addWidget(self._managed_button("选择 XLSX / CSV 文件", self._choose_files, True))
        top.addWidget(self._managed_button("移除选中", self._remove_file))
        top.addWidget(self._managed_button("清空列表", self._clear_files))
        top.addStretch(1)
        top.addWidget(self._managed_button("下载导入模板", self._export_template))
        layout.addLayout(top)
        layout.addWidget(_label(
            "必需字段：车牌号、过车时间。可补充卡口、行政区域、车辆类型、所属企业、位置标签和经纬度。\n"
            "同一文件可包含多辆车；兼容旧版以文件名表示车牌的单车文件。Excel 请使用 .xlsx 格式。", "muted", True))
        self.file_list = QListWidget()
        self.file_list.setObjectName("files")
        self.file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.file_list.setMinimumHeight(90)
        self.file_list.setMaximumHeight(135)
        layout.addWidget(self.file_list)
        run_row = QHBoxLayout()
        self.import_file_count = _label("尚未选择文件", "muted")
        run_row.addWidget(self.import_file_count, 1)
        run_row.addWidget(self._managed_button("开始校验并导入", self._import_selected, True))
        layout.addLayout(run_row)
        self.import_result = _label("导入完成后将在这里显示新增记录、重复记录和数据问题。", "muted", True)
        layout.addWidget(self.import_result)
        tabs = QTabWidget()
        errors_page = QWidget()
        errors_layout = QVBoxLayout(errors_page)
        errors_layout.setContentsMargins(10, 10, 10, 10)
        self.import_errors = _table(["源文件", "行号", "问题说明"])
        errors_layout.addWidget(self.import_errors)
        tabs.addTab(errors_page, "本次数据问题")
        history_page = QWidget()
        history_layout = QVBoxLayout(history_page)
        history_layout.setContentsMargins(10, 10, 10, 10)
        self.import_history = _table(["导入时间", "批次", "新增记录", "重复记录", "问题数", "来源"])
        history_layout.addWidget(self.import_history)
        tabs.addTab(history_page, "导入历史")
        layout.addWidget(tabs, 1)

    def _build_events(self):
        layout = self._new_page()
        filters = QGridLayout()
        filters.setHorizontalSpacing(9)
        self.event_keyword = QLineEdit()
        self.event_keyword.setPlaceholderText("车牌 / 企业 / 事件标题")
        self.event_keyword.returnPressed.connect(self._refresh_events)
        self.event_level = QComboBox()
        self.event_level.addItem("全部关注等级", None)
        for number in (1, 2, 3):
            self.event_level.addItem(LEVEL_NAMES[number], number)
        self.event_type = QComboBox()
        self.event_type.addItem("全部事件类型", None)
        filters.addWidget(self.event_keyword, 0, 0, 1, 2)
        filters.addWidget(self.event_level, 0, 2)
        filters.addWidget(self.event_type, 0, 3)
        self.date_from_check = QCheckBox("起始日期")
        self.event_date_from = QDateEdit(QDate.currentDate().addMonths(-1))
        self.event_date_from.setDisplayFormat("yyyy-MM-dd")
        self.event_date_from.setCalendarPopup(True)
        self.event_date_from.setEnabled(False)
        self.date_from_check.toggled.connect(self.event_date_from.setEnabled)
        self.date_to_check = QCheckBox("结束日期")
        self.event_date_to = QDateEdit(QDate.currentDate())
        self.event_date_to.setDisplayFormat("yyyy-MM-dd")
        self.event_date_to.setCalendarPopup(True)
        self.event_date_to.setEnabled(False)
        self.date_to_check.toggled.connect(self.event_date_to.setEnabled)
        dates = QHBoxLayout()
        dates.addWidget(self.date_from_check)
        dates.addWidget(self.event_date_from)
        dates.addSpacing(10)
        dates.addWidget(self.date_to_check)
        dates.addWidget(self.event_date_to)
        dates.addStretch(1)
        filters.addLayout(dates, 1, 0, 1, 3)
        buttons = QHBoxLayout()
        buttons.addWidget(_button("重置", self._reset_event_filters))
        buttons.addWidget(_button("筛选", self._refresh_events, True))
        filters.addLayout(buttons, 1, 3)
        filters.setColumnStretch(0, 1)
        filters.setColumnStretch(1, 1)
        layout.addLayout(filters)
        row = QHBoxLayout()
        self.event_count = _label("0 条事件", "muted")
        row.addWidget(self.event_count, 1)
        row.addWidget(_button("查看选中车辆", lambda: self._open_table_vehicle(self.events_table)))
        layout.addLayout(row)
        splitter = QSplitter(Qt.Vertical)
        self.events_table = _table(["关注等级", "车牌号", "事件类型", "开始时间", "结束时间", "分值", "事件标题"])
        self.events_table.itemSelectionChanged.connect(self._show_event_evidence)
        self.events_table.cellDoubleClicked.connect(lambda *_: self._open_table_vehicle(self.events_table))
        splitter.addWidget(self.events_table)
        self.event_evidence = QTextEdit()
        self.event_evidence.setReadOnly(True)
        self.event_evidence.setMinimumHeight(105)
        self.event_evidence.setPlaceholderText("选择事件以查看触发依据、关联记录和数据限制。双击事件可进入车辆详情。")
        splitter.addWidget(self.event_evidence)
        splitter.setSizes([370, 150])
        layout.addWidget(splitter, 1)

    def _build_vehicle(self):
        layout = self._new_page()
        choose = QHBoxLayout()
        choose.addWidget(_label("选择车辆"))
        self.vehicle_picker = QComboBox()
        self.vehicle_picker.setEditable(True)
        self.vehicle_picker.setInsertPolicy(QComboBox.NoInsert)
        self.vehicle_picker.setMinimumWidth(190)
        self.vehicle_picker.activated.connect(lambda *_: self._select_vehicle())
        self.vehicle_picker.lineEdit().returnPressed.connect(self._select_vehicle)
        choose.addWidget(self.vehicle_picker, 1)
        choose.addWidget(_button("查询", self._select_vehicle, True))
        choose.addWidget(self._managed_button("导出该车 Word 报告", self._export_current_vehicle))
        layout.addLayout(choose)
        cards = QHBoxLayout()
        self.vehicle_metrics = {}
        for key, title in [("risk", "当前关注等级"), ("records", "过车记录"), ("events", "风险事件"), ("night", "夜间过车占比")]:
            metric = MetricCard(title)
            if key == "risk":
                metric.value.setStyleSheet("font-size: 21px;")
            self.vehicle_metrics[key] = metric
            cards.addWidget(metric, 1)
        layout.addLayout(cards)
        self.vehicle_info = _label("尚无车辆数据。请先导入文件，或从风险事件中选择车辆。", "muted", True)
        self.vehicle_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.vehicle_info)
        self.vehicle_assessment = _label("", "muted", True)
        self.vehicle_assessment.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.vehicle_assessment)
        tabs = QTabWidget()
        trajectory = QWidget()
        trajectory_layout = QVBoxLayout(trajectory)
        trajectory_layout.setContentsMargins(9, 9, 9, 9)
        trajectory_layout.addWidget(_label("按过车时间排序。轨迹以真实导入记录展示，不补造缺失路段。", "muted", True))
        self.trajectory_table = _table(["过车时间", "卡口名称", "行政区域", "位置标签", "卡口类型", "经度", "纬度"])
        trajectory_layout.addWidget(self.trajectory_table, 1)
        tabs.addTab(trajectory, "过车时间轴")
        event_page = QWidget()
        event_layout = QVBoxLayout(event_page)
        event_layout.setContentsMargins(9, 9, 9, 9)
        self.vehicle_events = _table(["关注等级", "事件类型", "开始时间", "结束时间", "事件标题"])
        self.vehicle_events.itemSelectionChanged.connect(self._show_vehicle_evidence)
        event_layout.addWidget(self.vehicle_events, 3)
        self.vehicle_evidence = QTextEdit()
        self.vehicle_evidence.setReadOnly(True)
        self.vehicle_evidence.setPlaceholderText("选择上方事件查看证据。没有事件只表示当前规则未触发。")
        self.vehicle_evidence.setMinimumHeight(85)
        event_layout.addWidget(self.vehicle_evidence, 2)
        tabs.addTab(event_page, "事件与证据")
        history_page = QWidget()
        history_layout = QVBoxLayout(history_page)
        history_layout.setContentsMargins(9, 9, 9, 9)
        history_layout.addWidget(_label("这里记录导入或重新分析的结果。同一数据的重复分析不代表车辆发生了新的独立行程。", "muted", True))
        self.vehicle_history = _table(["分析时间", "规则版本", "关注等级", "事件数", "说明"])
        history_layout.addWidget(self.vehicle_history, 1)
        tabs.addTab(history_page, "分析历史")
        layout.addWidget(tabs, 1)

    def _build_reports(self):
        layout = self._new_page()
        toolbar = QHBoxLayout()
        self.report_keyword = QLineEdit()
        self.report_keyword.setPlaceholderText("按车牌 / 企业筛选导出范围")
        self.report_keyword.returnPressed.connect(self._refresh_reports)
        toolbar.addWidget(self.report_keyword, 1)
        toolbar.addWidget(_button("筛选", self._refresh_reports))
        toolbar.addWidget(self._managed_button("导出列表 Excel", self._export_rankings, True))
        toolbar.addWidget(self._managed_button("导出选中车辆 Word", self._export_selected_report))
        layout.addLayout(toolbar)
        self.report_count = _label("0 辆车", "muted", True)
        layout.addWidget(self.report_count)
        self.report_table = _table(["关注等级", "车牌号", "车辆类型", "所属企业", "记录数", "事件数", "最近过车"])
        self.report_table.cellDoubleClicked.connect(lambda *_: self._open_table_vehicle(self.report_table))
        layout.addWidget(self.report_table, 1)
        information = _label(
            "Excel 包含当前筛选范围内的车辆排名与事件依据；Word 包含选中车辆的画像、过车记录、事件证据和规则版本。\n"
            "报告中的风险事件属于辅助核查线索，分值与关注等级不等同于违法认定。", "muted", True)
        layout.addWidget(information)

    def _build_settings(self):
        layout = self._new_page()
        self.settings_note = _label("当前规则参数", "muted", True)
        layout.addWidget(self.settings_note)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        contents = QWidget()
        grid = QGridLayout(contents)
        grid.setContentsMargins(0, 0, 7, 0)
        grid.setSpacing(14)
        definitions = [
            ("疑似短停与重点区域", [
                ("short_stop_min", "短停间隔下限（分钟）", 1, 1440, "近距离连续记录之间的时间间隔下限。"),
                ("short_stop_max", "短停间隔上限（分钟）", 1, 10000, "超过上限的记录不作为短停判断。"),
                ("near_distance_km", "邻近距离（公里）", 0.01, 50.0, "有经纬度时，用于判断两条记录的位置是否邻近。"),
                ("sensitive_stay_minutes", "重点区域间隔下限（分钟）", 1, 10000, "位置标签命中重点区域时采用的时间阈值。"),
                ("long_stay_minutes", "长时间间隔阈值（分钟）", 1, 10000, "同卡口或邻近记录的长时间间隔阈值。"),
            ]),
            ("夜间活动与高频往返", [
                ("night_start", "夜间开始（小时）", 0, 23, "24 小时制，包含开始小时。"),
                ("night_end", "夜间结束（小时）", 0, 23, "24 小时制，不包含结束小时。"),
                ("frequent_window_hours", "往返统计窗口（小时）", 1, 168, "在此时间窗口内统计重复到访。"),
                ("frequent_min_visits", "区域重复到访次数", 2, 100, "每次到访之间须有其他行政区域的过车观测。"),
            ]),
            ("高速返回与企业群体", [
                ("highway_return_hours", "高速返回窗口（小时）", 1, 168, "离开高速后，在此时间内再次进入的检测窗口。"),
                ("company_window_hours", "企业群体窗口（小时）", 1, 168, "统计同一企业多车活动的时间窗口。"),
                ("company_min_vehicles", "企业群体最少车辆", 2, 100, "触发群体线索所需的不同车牌数。"),
            ]),
        ]
        for position, (title, fields) in enumerate(definitions):
            box = QGroupBox(title)
            form = QFormLayout(box)
            form.setContentsMargins(14, 20, 14, 14)
            form.setVerticalSpacing(12)
            form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            for key, label, minimum, maximum, tip in fields:
                if isinstance(minimum, float):
                    widget = QDoubleSpinBox()
                    widget.setDecimals(2)
                    widget.setSingleStep(0.1)
                else:
                    widget = QSpinBox()
                widget.setRange(minimum, maximum)
                widget.setToolTip(tip)
                field_label = _label(label)
                field_label.setToolTip(tip)
                self._settings_widgets[key] = widget
                form.addRow(field_label, widget)
            grid.addWidget(box, position // 2, position % 2, Qt.AlignTop)
        rule_info = _label(
            "判定依赖导入数据的完整性。没有经纬度时仅在同一卡口记录之间推断间隔；行政区域相同不会直接认定停车。\n"
            "位置标签、卡口类型和企业字段缺失时，对应规则可能无法触发。", "muted", True)
        grid.addWidget(rule_info, 1, 1, Qt.AlignTop)
        grid.setRowStretch(2, 1)
        scroll.setWidget(contents)
        layout.addWidget(scroll, 1)
        actions = QHBoxLayout()
        actions.addWidget(self._managed_button("恢复默认参数", self._restore_defaults))
        actions.addStretch(1)
        actions.addWidget(self._managed_button("使用现有参数重新分析", self._reanalyze))
        actions.addWidget(self._managed_button("保存参数并重新分析", self._save_settings, True))
        layout.addLayout(actions)

    @Slot(int)
    def _change_page(self, index):
        if not hasattr(self, "pages") or index < 0 or index >= self.pages.count():
            return
        self.pages.setCurrentIndex(index)
        self.page_title.setText(self.PAGE_NAMES[index])
        self.page_subtitle.setText(self.PAGE_DESCRIPTIONS[index])

    @Slot()
    def _refresh_all(self):
        try:
            self._vehicles = list(self.service.list_vehicles())
            self._events = list(self.service.list_events())
            summary = self.service.summary()
            self._refresh_dashboard(summary)
            self._refresh_import_history()
            self._refresh_event_types()
            self._refresh_events()
            self._refresh_vehicle_picker()
            if self._detail:
                self._show_vehicle(_vehicle_key(self._detail["vehicle"]), navigate=False)
            self._refresh_reports()
            self._load_settings()
        except Exception as exc:
            self._error("读取数据失败", str(exc))

    def _refresh_dashboard(self, summary):
        for key, card in self.dashboard_metrics.items():
            card.set_value(summary.get(key, 0), "#c53a46" if key == "level1" and summary.get(key) else None)
        start, end = summary.get("coverage_start"), summary.get("coverage_end")
        self.coverage_label.setText("数据覆盖：{}  至  {}".format(start, end) if start else "尚未导入有效过车数据")
        self.dashboard_empty.setVisible(not bool(self._vehicles))
        counts = summary.get("event_types", {})
        if isinstance(counts, dict):
            distribution = [{"type": key, "count": value} for key, value in counts.items()]
        else:
            distribution = [{"type": item.get("event_type", item.get("type", "")), "count": item.get("count", 0)} for item in counts]
        distribution.sort(key=lambda item: -int(item["count"]))
        _populate(self.event_distribution, distribution, ["type", "count"])
        priority = sorted(
            (row for row in self._vehicles if row.get("event_count", 0)),
            key=lambda row: (int(row.get("risk_level", 0) or 9), -int(row.get("event_count", 0)), row.get("plate", "")),
        )
        _populate(self.priority_table, priority[:30], [lambda row: _level(row.get("risk_level")), _vehicle_name, "event_count", "last_seen"], 0)
        self.dashboard_foot.setText("二级事件 {} 条   ·   三级事件 {} 条   ·   最近导入 {}".format(
            summary.get("level2", 0), summary.get("level3", 0), summary.get("last_import") or "暂无"))

    def _refresh_import_history(self):
        rows = self.service.imports()
        _populate(self.import_history, rows, [
            lambda row: row.get("created_at", row.get("imported_at", row.get("time"))),
            lambda row: row.get("batch_id", row.get("id")),
            lambda row: row.get("new_records", row.get("record_count", 0)),
            "duplicate_count", "error_count",
            lambda row: row.get("files", row.get("sources", row.get("source_files", ""))),
        ])

    def _refresh_event_types(self):
        current = self.event_type.currentData()
        self.event_type.blockSignals(True)
        self.event_type.clear()
        self.event_type.addItem("全部事件类型", None)
        for event_type in sorted({event.get("event_type", "") for event in self._events if event.get("event_type")}):
            self.event_type.addItem("{} · {}".format(event_type, EVENT_TYPES.get(event_type, event_type)), event_type)
        found = self.event_type.findData(current)
        self.event_type.setCurrentIndex(found if found >= 0 else 0)
        self.event_type.blockSignals(False)

    def _event_filters(self):
        filters = {}
        keyword = self.event_keyword.text().strip()
        if keyword:
            filters["keyword"] = keyword
        if self.event_level.currentData() is not None:
            filters["level"] = self.event_level.currentData()
        if self.event_type.currentData():
            filters["event_type"] = self.event_type.currentData()
        if self.date_from_check.isChecked():
            filters["date_from"] = self.event_date_from.date().toString("yyyy-MM-dd")
        if self.date_to_check.isChecked():
            filters["date_to"] = self.event_date_to.date().toString("yyyy-MM-dd")
        return filters

    @Slot()
    def _refresh_events(self):
        filters = self._event_filters()
        if filters.get("date_from", "") > filters.get("date_to", "9999-12-31"):
            self._info("日期范围无效", "起始日期应早于或等于结束日期。")
            return
        rows = self.service.list_events(filters)
        _populate(self.events_table, rows, [lambda row: _level(row.get("level")), _vehicle_name, lambda row: "{} · {}".format(row.get("event_type", ""), EVENT_TYPES.get(row.get("event_type"), row.get("event_type", ""))), "start", "end", "score", "title"], 0)
        self.event_count.setText("共 {} 条事件 · 选择一行查看证据，双击进入车辆详情".format(len(rows)) if rows else "没有符合筛选条件的事件")
        self.event_evidence.clear()

    def _reset_event_filters(self):
        self.event_keyword.clear()
        self.event_level.setCurrentIndex(0)
        self.event_type.setCurrentIndex(0)
        self.date_from_check.setChecked(False)
        self.date_to_check.setChecked(False)
        self._refresh_events()

    def _evidence_text(self, event):
        lines = [
            "{}  |  {}  |  {}".format(_vehicle_name(event), _level(event.get("level")), event.get("title", "")),
            "时间：{}  至  {}".format(_text(event.get("start")), _text(event.get("end"))),
            "事件类型：{}    模型：{}    分值：{}".format(_text(event.get("event_type")), _text(event.get("model", "通用")), event.get("score", 0)),
            "", "触发依据：",
        ]
        evidence = event.get("evidence") or []
        if isinstance(evidence, str):
            evidence = [evidence]
        lines.extend("• " + _text(value) for value in evidence)
        if not evidence:
            lines.append("未提供详细依据。")
        quality = event.get("data_quality") or []
        if isinstance(quality, str):
            quality = [quality]
        if quality:
            lines.extend(["", "数据限制："] + ["• " + _text(value) for value in quality])
        lines.extend(["", "关联记录数：{}    事件编号：{}".format(len(event.get("record_keys") or []), _text(event.get("event_id")))])
        return "\n".join(lines)

    def _show_event_evidence(self):
        row = _selected(self.events_table)
        self.event_evidence.setPlainText(self._evidence_text(row) if row else "")

    def _show_vehicle_evidence(self):
        row = _selected(self.vehicle_events)
        self.vehicle_evidence.setPlainText(self._evidence_text(row) if row else "")

    def _refresh_vehicle_picker(self):
        current = self.vehicle_picker.currentText()
        current_key = self.vehicle_picker.currentData()
        self.vehicle_picker.blockSignals(True)
        self.vehicle_picker.clear()
        for row in self._vehicles:
            self.vehicle_picker.addItem(_vehicle_name(row), _vehicle_key(row))
        index = self.vehicle_picker.findData(current_key) if current_key else -1
        if index >= 0:
            self.vehicle_picker.setCurrentIndex(index)
        elif current:
            self.vehicle_picker.setCurrentText(current)
        self.vehicle_picker.blockSignals(False)
        if self.vehicle_picker.completer():
            self.vehicle_picker.completer().setCaseSensitivity(Qt.CaseInsensitive)
            self.vehicle_picker.completer().setFilterMode(Qt.MatchContains)

    @Slot()
    def _select_vehicle(self):
        text = self.vehicle_picker.currentText().strip()
        if not text:
            self._info("请选择车辆", "导入过车数据后，在这里输入或选择车牌号。")
            return
        current_index = self.vehicle_picker.currentIndex()
        if current_index >= 0 and text == self.vehicle_picker.itemText(current_index):
            key = self.vehicle_picker.itemData(current_index)
        else:
            matches = [row for row in self._vehicles if row.get("plate", "").upper() == text.upper()]
            if len(matches) > 1:
                self._info("请选择号牌类型", "此车牌存在多种号牌类型，请从下拉列表中选择具体车辆。")
                return
            key = _vehicle_key(matches[0]) if matches else text.upper()
        self._show_vehicle(key)

    def _show_vehicle(self, plate, navigate=True):
        detail = self.service.vehicle_detail(plate)
        if not detail:
            self._info("没有找到车辆", "未找到车牌 {} 的记录，请检查车牌或先导入数据。".format(plate))
            return
        self._detail = detail
        vehicle = detail["vehicle"]
        index = self.vehicle_picker.findData(_vehicle_key(vehicle))
        if index >= 0:
            self.vehicle_picker.setCurrentIndex(index)
        else:
            self.vehicle_picker.setCurrentText(_vehicle_name(vehicle))
        self.vehicle_metrics["risk"].set_value(_level(vehicle.get("risk_level")))
        self.vehicle_metrics["risk"].value.setStyleSheet("font-size: 20px; color: {};".format(LEVEL_COLORS.get(vehicle.get("risk_level", 0), "#62738a")))
        self.vehicle_metrics["records"].set_value(vehicle.get("record_count", len(detail.get("records", []))))
        self.vehicle_metrics["events"].set_value(vehicle.get("event_count", len(detail.get("events", []))))
        self.vehicle_metrics["night"].set_value(_ratio(vehicle.get("night_ratio")))
        self.vehicle_info.setText(
            "{}   车型：{}   号牌类型：{}   企业：{}\n"
            "主要区域：{}   首次记录：{}   最近记录：{}   规则版本：{}".format(
                vehicle.get("plate", plate), _text(vehicle.get("vehicle_type")), _text(vehicle.get("plate_type")),
                _text(vehicle.get("owner")), _text(vehicle.get("main_areas")), _text(vehicle.get("first_seen")),
                _text(vehicle.get("last_seen")), _text(detail.get("rule_version"))))
        assessments = vehicle.get("assessments") or {}
        self.vehicle_assessment.setText("规则适用情况：" + _text(assessments) if assessments else "")
        records = sorted(detail.get("records", []), key=lambda row: row.get("time", ""))
        _populate(self.trajectory_table, records, ["time", "checkpoint", "area", "location_tag", "checkpoint_type", "longitude", "latitude"])
        self.trajectory_table.sortItems(0, Qt.AscendingOrder)
        _populate(self.vehicle_events, detail.get("events", []), [lambda row: _level(row.get("level")), lambda row: EVENT_TYPES.get(row.get("event_type"), row.get("event_type")), "start", "end", "title"], 0)
        self.vehicle_evidence.clear()
        _populate(self.vehicle_history, detail.get("history", []), [
            lambda row: row.get("created_at", row.get("analyzed_at", row.get("time"))),
            "rule_version", lambda row: _level(row.get("risk_level", row.get("level"))),
            "event_count", lambda row: row.get("reason", row.get("action", row.get("source", "分析快照"))),
        ])
        if navigate:
            self.navigation.setCurrentRow(3)

    def _open_table_vehicle(self, table):
        row = _selected(table)
        if row and row.get("plate"):
            self._show_vehicle(_vehicle_key(row))
        else:
            self._info("请选择记录", "先在表格中选择一辆车或一条事件。")

    @Slot()
    def _refresh_reports(self):
        self._report_vehicles = self.service.list_vehicles(self.report_keyword.text().strip())
        _populate(self.report_table, self._report_vehicles, [lambda row: _level(row.get("risk_level")), _vehicle_name, "vehicle_type", "owner", "record_count", "event_count", "last_seen"], 0)
        self.report_count.setText("当前导出范围：{} 辆车。Excel 导出本列表；Word 导出选中车辆。".format(len(self._report_vehicles)))

    def _choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "选择过车数据文件", "", "过车数据 (*.xlsx *.csv);;Excel (*.xlsx);;CSV (*.csv)")
        self._add_files(paths)

    def _add_files(self, paths):
        existing = {self.file_list.item(index).data(Qt.UserRole) for index in range(self.file_list.count())}
        for path in paths:
            absolute = str(Path(path).resolve())
            if absolute not in existing:
                item = QListWidgetItem(Path(absolute).name)
                item.setData(Qt.UserRole, absolute)
                item.setToolTip(absolute)
                self.file_list.addItem(item)
                existing.add(absolute)
        self._update_file_count()

    def _remove_file(self):
        for item in self.file_list.selectedItems():
            self.file_list.takeItem(self.file_list.row(item))
        self._update_file_count()

    def _clear_files(self):
        self.file_list.clear()
        self._update_file_count()

    def _update_file_count(self):
        count = self.file_list.count()
        self.import_file_count.setText("已选择 {} 个文件".format(count) if count else "尚未选择文件")

    def _import_selected(self):
        paths = [self.file_list.item(index).data(Qt.UserRole) for index in range(self.file_list.count())]
        if not paths:
            self._info("尚未选择文件", "请先选择一个或多个 XLSX / CSV 文件。")
            return
        self._start_job("校验、导入并分析数据", lambda: self.service.import_files(paths), self._after_import)

    def _import_demo(self):
        path = _resource_path("samples/demo.xlsx")
        if not path.exists():
            self._error("演示文件缺失", "未找到内置合成数据文件：{}".format(path))
            return
        self._start_job("载入合成演示数据", lambda: self.service.import_files([str(path)]), self._after_import)

    def _after_import(self, result):
        self._refresh_all()
        errors = result.get("errors") or []
        _populate(self.import_errors, errors, [
            lambda row: Path(str(row.get("file", row.get("source", "")))).name,
            lambda row: row.get("row", row.get("row_number", "")),
            lambda row: row.get("message", row.get("error", row.get("reason", ""))),
        ])
        message = "导入完成：新增 {} 条，重复 {} 条，问题 {} 条，当前事件 {} 条。".format(
            result.get("new_records", result.get("record_count", 0)), result.get("duplicate_count", 0),
            result.get("error_count", len(errors)), result.get("event_count", 0))
        warnings = result.get("warnings") or []
        if warnings:
            message += "\n" + "\n".join(str(value) for value in warnings)
        self.import_result.setText(message)
        self.navigation.setCurrentRow(1)
        self.statusBar().showMessage(message.split("\n")[0], 12000)

    def _export_template(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存过车数据模板", "过车数据导入模板.xlsx", "Excel 工作簿 (*.xlsx)")
        if path:
            path = self._prepare_output_path(path, ".xlsx")
            if path:
                self._start_job("生成导入模板", lambda: create_template(path, metadata=self._metadata()), self._after_export)

    def _metadata(self):
        metadata = dict(self.service.summary())
        metadata.update({"system": APP_TITLE, "data_source": "本机已导入过车记录", "allow_overwrite": True})
        return metadata

    def _prepare_output_path(self, path, suffix):
        output = _file_suffix(path, suffix)
        # QFileDialog returns the exact filename typed by the user when its
        # extension already matches the selected filter.  Prompt in both
        # cases; checking only ``output != path`` used to silently replace an
        # existing .xlsx/.docx report.
        if Path(output).exists():
            box = QMessageBox(self)
            box.setWindowTitle("确认替换文件")
            box.setIcon(QMessageBox.Question)
            box.setTextFormat(Qt.PlainText)
            box.setText("文件已经存在，是否替换？\n{}".format(output))
            replace = box.addButton("替换", QMessageBox.AcceptRole)
            box.addButton("取消", QMessageBox.RejectRole)
            box.exec_()
            if box.clickedButton() != replace:
                return None
        return output

    def _export_rankings(self):
        if not self._report_vehicles:
            self._info("没有可导出的数据", "请先导入数据，或调整列表筛选条件。")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出车辆风险排名", "车辆风险排名.xlsx", "Excel 工作簿 (*.xlsx)")
        if not path:
            return
        path = self._prepare_output_path(path, ".xlsx")
        if not path:
            return
        vehicles = list(self._report_vehicles)
        identities = {_vehicle_key(row) for row in vehicles}
        events = [row for row in self._events if _vehicle_key(row) in identities]
        metadata = self._metadata()
        self._start_job("导出车辆排名 Excel", lambda: export_rankings(vehicles, events, path, metadata), self._after_export)

    def _export_selected_report(self):
        row = _selected(self.report_table)
        if not row:
            self._info("请选择车辆", "在列表中选择一辆车，再导出 Word 研判报告。")
            return
        detail = self.service.vehicle_detail(_vehicle_key(row))
        self._export_vehicle(detail)

    def _export_current_vehicle(self):
        if not self._detail:
            self._info("请选择车辆", "先查询车辆详情，再导出 Word 研判报告。")
            return
        self._export_vehicle(self._detail)

    def _export_vehicle(self, detail):
        if not detail:
            return
        plate = detail["vehicle"]["plate"]
        # Do not let imported display text become an invalid Windows filename.
        safe_plate = "".join("_" if char in '<>:"/\\|?*' else char for char in _vehicle_name(detail["vehicle"]))
        path, _ = QFileDialog.getSaveFileName(self, "导出单车研判报告", safe_plate + "_风险研判报告.docx", "Word 文档 (*.docx)")
        if path:
            path = self._prepare_output_path(path, ".docx")
            if path:
                metadata = self._metadata()
                metadata["rule_version"] = detail.get("rule_version", metadata.get("rule_version", ""))
                self._start_job("导出单车 Word 报告", lambda: export_vehicle_report(detail, path, metadata), self._after_export)

    def _after_export(self, path):
        self._info("文件已保存", "保存位置：\n{}".format(path))

    def _load_settings(self):
        settings = self.service.get_settings()
        rules = settings.get("rules", settings)
        for key, widget in self._settings_widgets.items():
            if key in rules:
                widget.setValue(rules[key])
        version = settings.get("rule_version", settings.get("version", ""))
        self.settings_note.setText("规则版本：{}。保存会更新参数并重新生成事件，不会修改原始过车记录。".format(version or "当前本地配置"))

    def _restore_defaults(self):
        for key, value in asdict(RuleConfig()).items():
            if key in self._settings_widgets:
                self._settings_widgets[key].setValue(value)
        self.settings_note.setText("已在界面恢复默认值。点击“保存参数并重新分析”后生效。")

    def _save_settings(self):
        settings = {key: widget.value() for key, widget in self._settings_widgets.items()}
        if settings["short_stop_min"] > settings["short_stop_max"]:
            self._info("参数范围无效", "短停间隔下限不能大于上限。")
            return
        if settings["night_start"] == settings["night_end"]:
            self._info("夜间时段无效", "夜间开始小时与结束小时不能相同。")
            return
        self._start_job("保存规则并重新分析", lambda: self.service.save_settings(settings), self._after_reanalysis)

    def _reanalyze(self):
        self._start_job("使用已保存规则重新分析", self.service.reanalyze, self._after_reanalysis)

    def _after_reanalysis(self, result):
        self._refresh_all()
        count = result.get("event_count", self.service.summary().get("events", 0)) if isinstance(result, dict) else self.service.summary().get("events", 0)
        self._info("重新分析完成", "当前共有 {} 条风险事件。请在风险事件或车辆详情中查看依据。".format(count))

    def _start_job(self, name, task, callback):
        if self._job is not None:
            self._info("正在处理任务", "{}，请等待当前任务完成。".format(self._job_name))
            return
        self._job_name = name
        self._job_callback = callback
        worker = TaskThread(task, self)
        self._job = worker
        worker.completed.connect(self._job_completed)
        worker.failed.connect(self._job_failed)
        worker.finished.connect(self._job_finished)
        self.progress.show()
        self.pages.setEnabled(False)
        self.statusBar().showMessage("正在{}…".format(name))
        for button in self._action_buttons:
            button.setEnabled(False)
        for widget in self._settings_widgets.values():
            widget.setEnabled(False)
        worker.start()

    @Slot(object)
    def _job_completed(self, result):
        try:
            if self._job_callback:
                self._job_callback(result)
        except Exception:
            self._error("显示处理结果失败", traceback.format_exc())

    @Slot(str)
    def _job_failed(self, details):
        self._error("{}失败".format(self._job_name), details.splitlines()[-1] if details else "未知错误", details)

    @Slot()
    def _job_finished(self):
        worker = self._job
        self._job = None
        self._job_callback = None
        self.progress.hide()
        self.pages.setEnabled(True)
        for button in self._action_buttons:
            button.setEnabled(True)
        for widget in self._settings_widgets.values():
            widget.setEnabled(True)
        self.statusBar().showMessage("就绪 · 所有数据均保存在本机", 10000)
        if worker:
            worker.deleteLater()

    def _info(self, title, text):
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Information)
        box.setTextFormat(Qt.PlainText)
        box.setText(text)
        box.addButton("确定", QMessageBox.AcceptRole)
        box.exec_()

    def _error(self, title, text, details=None):
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Warning)
        box.setTextFormat(Qt.PlainText)
        box.setText(text)
        if details:
            box.setDetailedText(details)
        box.addButton("确定", QMessageBox.AcceptRole)
        box.exec_()

    def closeEvent(self, event):
        if self._job is not None and self._job.isRunning():
            self._info("任务尚未完成", "正在{}。为避免数据或导出文件不完整，请等待任务结束后关闭。".format(self._job_name))
            event.ignore()
            return
        try:
            self.service.close()
        finally:
            event.accept()


def run_desktop(service):
    """Start the GUI, or show a window in an already-running QApplication."""
    existing = QApplication.instance()
    if existing is None:
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        app = QApplication(sys.argv)
        app.setApplicationName(APP_TITLE)
        app.setOrganizationName("TVRA")
        app.setStyle("Fusion")
        app.setFont(QFont("Microsoft YaHei", 9))
    else:
        app = existing
    window = MainWindow(service)
    window.show()
    # Preserve the window reference when a caller owns the existing event loop.
    app._tvra_main_window = window
    return app.exec_() if existing is None else 0
