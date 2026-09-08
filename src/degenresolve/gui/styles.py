"""
GUI styling for DegenResolve - Glacier dark theme

Color palette derived from Stitch design reference.
"""


def get_modern_theme_stylesheet() -> str:
    return """
        QMainWindow {
            background: #0a1020;
            color: #ffffff;
        }

        QTabWidget::pane {
            border: 1px solid #2a3a48;
            background: #0a1020;
            border-radius: 8px;
        }

        QTabBar::tab {
            background: #141c2e;
            color: #ffffff;
            padding: 14px 30px;
            margin: 3px;
            border: 1px solid #2a3a48;
            border-radius: 6px;
            font-weight: 600;
            font-size: 14px;
            min-width: 100px;
        }

        QTabBar::tab:selected {
            background: rgba(125, 211, 252, 0.1);
            color: #7dd3fc;
            border: 1px solid rgba(125, 211, 252, 0.3);
        }

        QTabBar::tab:hover {
            background: #1a2438;
            color: #ffffff;
        }

        QGroupBox {
            background: #0f1524;
            border: none;
            border-radius: 8px;
            margin-top: 28px;
            margin-bottom: 10px;
            padding: 20px 12px 12px 12px;
            font-weight: 600;
            font-size: 14px;
            color: #ffffff;
        }

        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 12px;
            top: 8px;
            padding: 6px 16px;
            border-radius: 4px;
            background: #0e4d6e;
            color: #7dd3fc;
            font-weight: 600;
            font-size: 13px;
        }

        QPushButton {
            background: rgba(125, 211, 252, 0.15);
            border: 1px solid rgba(125, 211, 252, 0.3);
            border-radius: 6px;
            color: #7dd3fc;
            padding: 8px 12px;
            font-weight: 600;
            font-size: 14px;
            min-height: 20px;
        }

        QPushButton:hover {
            background: rgba(125, 211, 252, 0.25);
            border: 1px solid rgba(125, 211, 252, 0.5);
        }

        QPushButton:pressed {
            background: rgba(125, 211, 252, 0.35);
        }

        QPushButton:disabled {
            background: #1a2438;
            color: #4a6070;
            border: 1px solid #2a3a48;
        }

        QPushButton#success {
            background: rgba(16, 185, 129, 0.15);
            border: 1px solid rgba(16, 185, 129, 0.3);
            color: #6ee7b7;
        }

        QPushButton#success:hover {
            background: rgba(16, 185, 129, 0.25);
            border: 1px solid rgba(16, 185, 129, 0.5);
        }

        QPushButton#danger {
            background: rgba(255, 107, 107, 0.15);
            border: 1px solid rgba(255, 107, 107, 0.3);
            color: #ff6b6b;
        }

        QPushButton#danger:hover {
            background: rgba(255, 107, 107, 0.25);
            border: 1px solid rgba(255, 107, 107, 0.5);
        }

        QPushButton#info {
            background: rgba(200, 160, 240, 0.15);
            border: 1px solid rgba(200, 160, 240, 0.3);
            color: #c8a0f0;
        }

        QPushButton#info:hover {
            background: rgba(200, 160, 240, 0.25);
            border: 1px solid rgba(200, 160, 240, 0.5);
        }

        QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
            background: rgba(26, 36, 56, 0.4);
            border: 1px solid rgba(125, 211, 252, 0.1);
            border-radius: 6px;
            padding: 8px;
            color: #ffffff;
            font-size: 14px;
            selection-background-color: #0e4d6e;
        }

        QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
            border: 1px solid rgba(125, 211, 252, 0.5);
            background: rgba(26, 36, 56, 0.6);
        }

        QComboBox::drop-down {
            border: none;
            width: 20px;
        }

        QComboBox::down-arrow {
            image: none;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 5px solid #ffffff;
            margin-right: 5px;
        }

        QComboBox QAbstractItemView {
            background: #1a2438;
            border: 1px solid rgba(125, 211, 252, 0.2);
            border-radius: 6px;
            color: #ffffff;
            selection-background-color: #0e4d6e;
            selection-color: #ffffff;
            outline: none;
        }

        QComboBox QAbstractItemView::item {
            padding: 8px;
            border: none;
            background: transparent;
        }

        QComboBox QAbstractItemView::item:hover {
            background: #202c42;
            color: #ffffff;
        }

        QComboBox QAbstractItemView::item:selected {
            background: #0e4d6e;
            color: #ffffff;
        }

        QTextEdit {
            background: rgba(10, 14, 26, 0.8);
            border: 1px solid rgba(125, 211, 252, 0.1);
            border-radius: 6px;
            padding: 10px;
            color: #ffffff;
            font-size: 12px;
            line-height: 1.4;
        }

        QProgressBar {
            border: 1px solid rgba(125, 211, 252, 0.1);
            border-radius: 6px;
            text-align: center;
            background: #111828;
            color: #ffffff;
            font-weight: 600;
            font-size: 12px;
        }

        QProgressBar::chunk {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #7dd3fc, stop:1 #c8a0f0);
            border-radius: 4px;
        }

        QLabel {
            color: #ffffff;
            font-size: 14px;
        }

        QCheckBox, QRadioButton {
            color: #ffffff;
            font-size: 14px;
            spacing: 8px;
        }

        QCheckBox::indicator, QRadioButton::indicator {
            width: 16px;
            height: 16px;
            border: 1px solid rgba(125, 211, 252, 0.3);
            border-radius: 3px;
            background: rgba(26, 36, 56, 0.4);
        }

        QCheckBox::indicator:checked, QRadioButton::indicator:checked {
            background: rgba(125, 211, 252, 0.2);
            border: 1px solid #7dd3fc;
        }

        QTableWidget {
            background: #0f1524;
            alternate-background-color: #141c2e;
            border: 1px solid #2a3a48;
            border-radius: 6px;
            gridline-color: #2a3a48;
            color: #ffffff;
            font-size: 12px;
        }

        QHeaderView::section {
            background: #141c2e;
            color: #ffffff;
            padding: 8px;
            border: 1px solid #2a3a48;
            font-weight: 600;
            font-size: 12px;
        }

        QStatusBar {
            background: #0a0e1a;
            color: #ffffff;
            border-top: 1px solid #2a3a48;
            min-height: 23px;
            max-height: 25px;
            padding: 2px 5px;
            font-size: 12px;
        }

        QScrollBar:vertical {
            background: #0a0e1a;
            width: 8px;
            border-radius: 4px;
            margin: 0px;
        }

        QScrollBar::handle:vertical {
            background: rgba(125, 211, 252, 0.2);
            border-radius: 4px;
            min-height: 20px;
        }

        QScrollBar::handle:vertical:hover {
            background: rgba(125, 211, 252, 0.4);
        }

        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
        }

        QScrollArea {
            border: 1px solid #2a3a48;
            border-radius: 6px;
            background: transparent;
        }

        QWidget#config_widget {
            background: #0a1020;
            color: #ffffff;
        }

        QMessageBox {
            background: #0f1524;
            color: #ffffff;
            border: 1px solid rgba(125, 211, 252, 0.15);
            border-radius: 8px;
        }

        QMessageBox QLabel {
            background: transparent;
            color: #ffffff;
            font-size: 12px;
        }

        QMessageBox QPushButton {
            background: rgba(125, 211, 252, 0.15);
            border: 1px solid rgba(125, 211, 252, 0.3);
            border-radius: 6px;
            color: #7dd3fc;
            padding: 8px 16px;
            font-weight: 600;
            font-size: 14px;
            min-width: 80px;
            min-height: 25px;
        }

        QMessageBox QPushButton:hover {
            background: rgba(125, 211, 252, 0.25);
            border: 1px solid rgba(125, 211, 252, 0.5);
        }

        QMessageBox QPushButton:pressed {
            background: rgba(125, 211, 252, 0.35);
        }

        QDialog {
            background: #0f1524;
            color: #ffffff;
            border: 1px solid rgba(125, 211, 252, 0.15);
            border-radius: 8px;
        }

        QDialog QLabel {
            background: transparent;
            color: #ffffff;
            font-size: 12px;
        }

        QDialog QPushButton {
            background: rgba(125, 211, 252, 0.15);
            border: 1px solid rgba(125, 211, 252, 0.3);
            border-radius: 6px;
            color: #7dd3fc;
            padding: 8px 16px;
            font-weight: 600;
            font-size: 14px;
            min-width: 80px;
            min-height: 25px;
        }

        QDialog QPushButton:hover {
            background: rgba(125, 211, 252, 0.25);
            border: 1px solid rgba(125, 211, 252, 0.5);
        }

        QDialog QPushButton:pressed {
            background: rgba(125, 211, 252, 0.35);
        }
    """


def get_day_theme_stylesheet() -> str:
    return """
        QMainWindow {
            background: #ffffff;
            color: #1e293b;
        }

        QTabWidget::pane {
            border: 1px solid #cbd5e1;
            background: #ffffff;
            border-radius: 8px;
        }

        QTabBar::tab {
            background: #f1f5f9;
            color: #64748b;
            padding: 14px 30px;
            margin: 3px;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            font-weight: 600;
            font-size: 14px;
            min-width: 100px;
        }

        QTabBar::tab:selected {
            background: rgba(29, 78, 216, 0.1);
            color: #1d4ed8;
            border: 1px solid rgba(29, 78, 216, 0.3);
        }

        QTabBar::tab:hover {
            background: #e2e8f0;
            color: #1e293b;
        }

        QGroupBox {
            background: #f0f4f8;
            border: none;
            border-radius: 8px;
            margin-top: 28px;
            margin-bottom: 10px;
            padding: 20px 12px 12px 12px;
            font-weight: 600;
            font-size: 14px;
            color: #1e293b;
        }

        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 12px;
            top: 8px;
            padding: 6px 16px;
            border-radius: 4px;
            background: #bfdbfe;
            color: #1d4ed8;
            font-weight: 600;
            font-size: 13px;
        }

        QPushButton {
            background: rgba(29, 78, 216, 0.1);
            border: 1px solid rgba(29, 78, 216, 0.3);
            border-radius: 6px;
            color: #1d4ed8;
            padding: 8px 12px;
            font-weight: 600;
            font-size: 14px;
            min-height: 20px;
        }

        QPushButton:hover {
            background: rgba(29, 78, 216, 0.2);
            border: 1px solid rgba(29, 78, 216, 0.5);
        }

        QPushButton:pressed {
            background: rgba(29, 78, 216, 0.3);
        }

        QPushButton:disabled {
            background: #f1f5f9;
            color: #94a3b8;
            border: 1px solid #cbd5e1;
        }

        QPushButton#success {
            background: rgba(5, 150, 105, 0.1);
            border: 1px solid rgba(5, 150, 105, 0.3);
            color: #059669;
        }

        QPushButton#success:hover {
            background: rgba(5, 150, 105, 0.2);
            border: 1px solid rgba(5, 150, 105, 0.5);
        }

        QPushButton#danger {
            background: rgba(220, 38, 38, 0.1);
            border: 1px solid rgba(220, 38, 38, 0.3);
            color: #dc2626;
        }

        QPushButton#danger:hover {
            background: rgba(220, 38, 38, 0.2);
            border: 1px solid rgba(220, 38, 38, 0.5);
        }

        QPushButton#info {
            background: rgba(124, 58, 237, 0.1);
            border: 1px solid rgba(124, 58, 237, 0.3);
            color: #7c3aed;
        }

        QPushButton#info:hover {
            background: rgba(124, 58, 237, 0.2);
            border: 1px solid rgba(124, 58, 237, 0.5);
        }

        QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
            background: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            padding: 8px;
            color: #1e293b;
            font-size: 14px;
            selection-background-color: #bfdbfe;
        }

        QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
            border: 1px solid rgba(29, 78, 216, 0.5);
            background: #f8fafc;
        }

        QComboBox::drop-down {
            border: none;
            width: 20px;
        }

        QComboBox::down-arrow {
            image: none;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 5px solid #64748b;
            margin-right: 5px;
        }

        QComboBox QAbstractItemView {
            background: #ffffff;
            border: 1px solid rgba(29, 78, 216, 0.2);
            border-radius: 6px;
            color: #1e293b;
            selection-background-color: #bfdbfe;
            selection-color: #1e293b;
            outline: none;
        }

        QComboBox QAbstractItemView::item {
            padding: 8px;
            border: none;
            background: transparent;
        }

        QComboBox QAbstractItemView::item:hover {
            background: #f1f5f9;
            color: #1e293b;
        }

        QComboBox QAbstractItemView::item:selected {
            background: #bfdbfe;
            color: #1e293b;
        }

        QTextEdit {
            background: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            padding: 10px;
            color: #1e293b;
            font-size: 12px;
            line-height: 1.4;
        }

        QProgressBar {
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            text-align: center;
            background: #f1f5f9;
            color: #1e293b;
            font-weight: 600;
            font-size: 12px;
        }

        QProgressBar::chunk {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #1d4ed8, stop:1 #7c3aed);
            border-radius: 4px;
        }

        QLabel {
            color: #1e293b;
            font-size: 14px;
        }

        QCheckBox, QRadioButton {
            color: #1e293b;
            font-size: 14px;
            spacing: 8px;
        }

        QCheckBox::indicator, QRadioButton::indicator {
            width: 16px;
            height: 16px;
            border: 1px solid rgba(29, 78, 216, 0.3);
            border-radius: 3px;
            background: #ffffff;
        }

        QCheckBox::indicator:checked, QRadioButton::indicator:checked {
            background: rgba(29, 78, 216, 0.2);
            border: 1px solid #1d4ed8;
        }

        QTableWidget {
            background: #f0f4f8;
            alternate-background-color: #f8fafc;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            gridline-color: #cbd5e1;
            color: #1e293b;
            font-size: 12px;
        }

        QHeaderView::section {
            background: #e2e8f0;
            color: #64748b;
            padding: 8px;
            border: 1px solid #cbd5e1;
            font-weight: 600;
            font-size: 12px;
        }

        QStatusBar {
            background: #f1f5f9;
            color: #64748b;
            border-top: 1px solid #cbd5e1;
            min-height: 23px;
            max-height: 25px;
            padding: 2px 5px;
            font-size: 12px;
        }

        QScrollBar:vertical {
            background: #f1f5f9;
            width: 8px;
            border-radius: 4px;
            margin: 0px;
        }

        QScrollBar::handle:vertical {
            background: rgba(29, 78, 216, 0.2);
            border-radius: 4px;
            min-height: 20px;
        }

        QScrollBar::handle:vertical:hover {
            background: rgba(29, 78, 216, 0.4);
        }

        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
        }

        QScrollArea {
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            background: transparent;
        }

        QWidget#config_widget {
            background: #ffffff;
            color: #1e293b;
        }

        QMessageBox {
            background: #f0f4f8;
            color: #1e293b;
            border: 1px solid rgba(29, 78, 216, 0.15);
            border-radius: 8px;
        }

        QMessageBox QLabel {
            background: transparent;
            color: #1e293b;
            font-size: 12px;
        }

        QMessageBox QPushButton {
            background: rgba(29, 78, 216, 0.1);
            border: 1px solid rgba(29, 78, 216, 0.3);
            border-radius: 6px;
            color: #1d4ed8;
            padding: 8px 16px;
            font-weight: 600;
            font-size: 14px;
            min-width: 80px;
            min-height: 25px;
        }

        QMessageBox QPushButton:hover {
            background: rgba(29, 78, 216, 0.2);
            border: 1px solid rgba(29, 78, 216, 0.5);
        }

        QMessageBox QPushButton:pressed {
            background: rgba(29, 78, 216, 0.3);
        }

        QDialog {
            background: #f0f4f8;
            color: #1e293b;
            border: 1px solid rgba(29, 78, 216, 0.15);
            border-radius: 8px;
        }

        QDialog QLabel {
            background: transparent;
            color: #1e293b;
            font-size: 12px;
        }

        QDialog QPushButton {
            background: rgba(29, 78, 216, 0.1);
            border: 1px solid rgba(29, 78, 216, 0.3);
            border-radius: 6px;
            color: #1d4ed8;
            padding: 8px 16px;
            font-weight: 600;
            font-size: 14px;
            min-width: 80px;
            min-height: 25px;
        }

        QDialog QPushButton:hover {
            background: rgba(29, 78, 216, 0.2);
            border: 1px solid rgba(29, 78, 216, 0.5);
        }

        QDialog QPushButton:pressed {
            background: rgba(29, 78, 216, 0.3);
        }
    """


DARK_COLORS = {
    "bg":          "#0a1020",
    "panel":       "#0f1524",
    "hover":       "#1a2438",
    "topbar":      "#1a2438",
    "border":      "#2a3a48",
    "text":        "#e0e8f0",
    "dim":         "#a0b4c4",
    "placeholder": "#4a6070",
    "accent":      "#7dd3fc",
    "green":       "#6ee7b7",
    "error":       "#ff6b6b",
    "warn":        "#f59e0b",
    "purple":      "#c8a0f0",
    "sel_bg":      "rgba(125,211,252,0.1)",
}
