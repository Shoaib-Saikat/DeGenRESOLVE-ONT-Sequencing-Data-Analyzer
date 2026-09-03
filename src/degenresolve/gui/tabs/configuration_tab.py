"""
Configuration tab for DegenResolve GUI

This module contains the configuration tab with all pipeline
parameter controls: coverage, ploidy, indel rules, variant calling,
filter mode, QC tools, and advanced criteria settings.
"""

import json
import os

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QScrollArea, QFormLayout, QSpinBox, QDoubleSpinBox,
    QComboBox, QCheckBox, QFileDialog, QMessageBox,
    QDialog, QTableWidget, QTableWidgetItem, QDialogButtonBox
)
from PyQt5.QtCore import Qt, QRectF, QThread, pyqtSignal, QSettings
from PyQt5.QtGui import QPainter, QColor

from ...utils import basecall


class BasecallDetectWorker(QThread):
    """Scans every read header in fastq_pass to determine each barcode's tier.

    Full scan rather than a sample: sampling cannot see a barcode that mixes
    basecall models, and that case is a hard error in the pipeline. Measured at
    ~1.3 s per barcode, so it stays off the UI thread.
    """

    detected = pyqtSignal(list)

    def __init__(self, fastq_pass, parent=None):
        super().__init__(parent)
        self.fastq_pass = fastq_pass

    def run(self):
        results = []
        try:
            barcodes = sorted(d for d in os.listdir(self.fastq_pass)
                              if os.path.isdir(os.path.join(self.fastq_pass, d)))
        except OSError:
            barcodes = []
        for name in barcodes:
            path = os.path.join(self.fastq_pass, name)
            files = basecall.barcode_files(path)
            if not files:
                continue
            info = basecall.detect(files)
            info["barcode"] = name
            info["signature"] = basecall.input_signature(path)
            results.append(info)
        self.detected.emit(results)


class ToggleSwitch(QCheckBox):
    """Sliding toggle switch - green/right when on, muted/left when off."""

    _OFF_TRACK  = "#2a3a48"
    _OFF_THUMB  = "#4a6070"
    _TEXT_COLOR = "#e0e8f0"

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)

    def set_dark(self, dark: bool):
        self._OFF_TRACK  = "#2a3a48" if dark else "#cbd5e1"
        self._OFF_THUMB  = "#4a6070" if dark else "#64748b"
        self._TEXT_COLOR = "#e0e8f0" if dark else "#1e293b"
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        track_w, track_h = 36, 18
        y = (self.height() - track_h) // 2

        if self.isChecked():
            p.setBrush(QColor("#10b981"))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(0, y, track_w, track_h), 9, 9)
            p.setBrush(QColor("#ffffff"))
            p.drawEllipse(QRectF(track_w - 16, y + 2, 14, 14))
        else:
            p.setBrush(QColor(self._OFF_TRACK))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(0, y, track_w, track_h), 9, 9)
            p.setBrush(QColor(self._OFF_THUMB))
            p.drawEllipse(QRectF(2, y + 2, 14, 14))

        if self.text():
            p.setPen(QColor(self._TEXT_COLOR))
            from PyQt5.QtGui import QFont
            p.setFont(QFont("Inter", 9))
            p.drawText(QRectF(track_w + 8, 0, self.width() - track_w - 8, self.height()),
                       Qt.AlignVCenter | Qt.AlignLeft, self.text())
        p.end()

    def hitButton(self, pos):
        return self.rect().contains(pos)


class ConfigurationTab(QWidget):
    """Configuration tab with all pipeline parameter controls."""

    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.setObjectName("config_widget")
        self._detection = []
        self._detect_worker = None
        self._fastq_pass = ""
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(400)
        scroll_widget = QWidget()
        scroll_widget.setObjectName("config_widget")
        scroll_layout = QVBoxLayout()
        scroll_layout.setSpacing(15)
        scroll_layout.setContentsMargins(15, 15, 15, 15)

        scroll_layout.addWidget(self._create_basecall_group())
        scroll_layout.addWidget(self._create_coverage_group())
        scroll_layout.addWidget(self._create_ploidy_group())
        scroll_layout.addWidget(self._create_indel_group())
        scroll_layout.addWidget(self._create_variant_group())
        scroll_layout.addWidget(self._create_filter_group())
        scroll_layout.addWidget(self._create_qualimap_group())
        scroll_layout.addWidget(self._create_nanoplot_group())
        scroll_layout.addWidget(self._create_parallel_group())
        scroll_layout.addWidget(self._create_advanced_group())
        scroll_layout.addWidget(self._create_config_buttons_group())
        scroll_layout.addStretch()

        scroll_widget.setLayout(scroll_layout)
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)
        self.setLayout(layout)

    # Basecall Model

    def _create_basecall_group(self):
        group = QGroupBox("Basecall Model")
        layout = QVBoxLayout()
        layout.setSpacing(10)

        self.basecall_summary = QLabel("No input directory selected.")
        self.basecall_summary.setWordWrap(True)
        self.basecall_summary.setStyleSheet("color: #64748b; font-size: 14px;")
        layout.addWidget(self.basecall_summary)

        row = QHBoxLayout()
        self.basecall_details_btn = QPushButton("Details...")
        self.basecall_details_btn.setEnabled(False)
        self.basecall_details_btn.clicked.connect(self._show_basecall_details)
        row.addWidget(self.basecall_details_btn)
        self.basecall_redetect_btn = QPushButton("Re-detect")
        self.basecall_redetect_btn.setEnabled(False)
        self.basecall_redetect_btn.clicked.connect(lambda: self.detect_basecall_models(force=True))
        row.addWidget(self.basecall_redetect_btn)
        row.addStretch()
        layout.addLayout(row)

        self.force_sup_check = ToggleSwitch("Force sup variant-calling profile")
        self.force_sup_check.setToolTip(
            "Applies bcftools' full ont-sup flag set regardless of the detected tier.\n\n"
            "This is NOT an indel-only switch. Enabling indel calling on non-sup reads "
            "requires dropping -I, which only happens by swapping in the whole sup "
            "profile - and that profile also changes -Q and --max-BQ, so SNV calls and "
            "degeneracy codes shift with it.\n\n"
            "hac carries -I on bcftools' own recommendation, so indels are reported as "
            "evidence rather than resolved. Override this only when you intend to apply "
            "the sup indel model to reads it was not tuned for."
        )
        self.force_sup_check.toggled.connect(self._on_auto_base_quality_changed)
        layout.addWidget(self.force_sup_check)

        self.basecall_warning = QLabel("")
        self.basecall_warning.setWordWrap(True)
        self.basecall_warning.setStyleSheet("color: #d97706; font-size: 13px;")
        self.basecall_warning.setVisible(False)
        layout.addWidget(self.basecall_warning)

        group.setLayout(layout)
        return group

    def set_working_directory(self, directory):
        """Point detection at a run directory and refresh from cache or scan."""
        self._fastq_pass = os.path.join(directory, "fastq_pass") if directory else ""
        self.detect_basecall_models()

    def _cache_key(self):
        return f"basecall_detection/{self._fastq_pass}"

    def _dir_signature(self):
        """Combined signature over every barcode, for cache invalidation."""
        try:
            names = sorted(d for d in os.listdir(self._fastq_pass)
                           if os.path.isdir(os.path.join(self._fastq_pass, d)))
        except OSError:
            return ""
        return "|".join(
            f"{n}={basecall.input_signature(os.path.join(self._fastq_pass, n))}"
            for n in names)

    def detect_basecall_models(self, force=False):
        """Detect per-barcode tiers, reusing the cache unless inputs changed."""
        if not self._fastq_pass or not os.path.isdir(self._fastq_pass):
            self._detection = []
            self.basecall_summary.setText("No fastq_pass directory found.")
            self.basecall_details_btn.setEnabled(False)
            self.basecall_redetect_btn.setEnabled(False)
            self._update_basecall_warning()
            return
        self.basecall_redetect_btn.setEnabled(True)

        sig = self._dir_signature()
        settings = QSettings("DegenResolve", "ONTAnalyzer")
        if not force:
            cached = settings.value(self._cache_key())
            if isinstance(cached, str) and cached:
                try:
                    blob = json.loads(cached)
                    if blob.get("signature") == sig:
                        self._apply_detection(blob.get("results", []))
                        return
                except (ValueError, TypeError):
                    pass

        self.basecall_summary.setText("Scanning read headers...")
        self.basecall_details_btn.setEnabled(False)
        # A directory change mid-scan would otherwise orphan the running thread.
        if self._detect_worker is not None and self._detect_worker.isRunning():
            self._detect_worker.requestInterruption()
            self._detect_worker.wait(2000)
        self._detect_worker = BasecallDetectWorker(self._fastq_pass, self)
        self._detect_worker.detected.connect(
            lambda res, s=sig: self._on_detected(res, s))
        self._detect_worker.start()

    def _on_detected(self, results, signature):
        QSettings("DegenResolve", "ONTAnalyzer").setValue(
            self._cache_key(), json.dumps({"signature": signature, "results": results}))
        self._apply_detection(results)

    def _apply_detection(self, results):
        self._detection = results or []
        if not self._detection:
            self.basecall_summary.setText("No barcodes with FASTQ files found.")
            self.basecall_details_btn.setEnabled(False)
            self._update_basecall_warning()
            return

        counts = {}
        for r in self._detection:
            counts[r["tier"]] = counts.get(r["tier"], 0) + 1
        parts = ", ".join(f"{n} {t}" for t, n in
                          sorted(counts.items(), key=lambda kv: -kv[1]))
        n = len(self._detection)
        text = f"{n} barcode{'s' if n != 1 else ''}: {parts}"

        flags = []
        if len(counts) > 1:
            flags.append("mixed tiers across barcodes")
        mixed = [r["barcode"] for r in self._detection if r["distinct"] > 1]
        if mixed:
            flags.append(f"{len(mixed)} barcode(s) mix basecall models - the run will abort")
        if counts.get("fast"):
            flags.append("fast basecalls are not intended for consensus refinement")
        if counts.get("unknown"):
            flags.append("some barcodes carry no model id; treated as hac")
        if flags:
            text += "  -  " + "; ".join(flags)

        self.basecall_summary.setText(text)
        self.basecall_details_btn.setEnabled(True)
        if getattr(self, "auto_base_quality_check", None) and \
                self.auto_base_quality_check.isChecked():
            self._on_auto_base_quality_changed()
        self._update_basecall_warning()

    def _update_basecall_warning(self):
        """Warn when the override contradicts the data, or decouples -Q/--max-BQ."""
        msgs = []
        if self.force_sup_check.isChecked():
            non_sup = [r for r in self._detection if r["tier"] != "sup"]
            if non_sup:
                msgs.append(
                    f"Override is on: {len(non_sup)} of {len(self._detection)} barcodes are "
                    f"not sup and will be processed with the sup profile anyway. This also "
                    f"moves -Q and --max-BQ, so degeneracy calls will shift.")
            if hasattr(self, "auto_base_quality_check") and \
                    not self.auto_base_quality_check.isChecked():
                msgs.append(
                    f"Base quality is pinned (-Q {self.min_base_quality_spin.value()} / "
                    f"--max-BQ {self.max_base_quality_spin.value()}). bcftools ships 1/35 for "
                    f"sup and 5/30 for hac; this pair is neither.")
        self.basecall_warning.setText("  ".join(msgs))
        self.basecall_warning.setVisible(bool(msgs))

    def _show_basecall_details(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Detected basecall models")
        dlg.resize(760, 420)
        lay = QVBoxLayout(dlg)
        table = QTableWidget(len(self._detection), 4, dlg)
        table.setHorizontalHeaderLabels(["Barcode", "Model", "Tier", "Indel calling"])
        forced = self.force_sup_check.isChecked()
        for row, r in enumerate(self._detection):
            tier = "sup" if forced else r["tier"]
            note = "on" if tier == "sup" else "off (-I)"
            if forced and r["tier"] != "sup":
                note += f"  [forced, detected {r['tier']}]"
            if r["distinct"] > 1:
                note = f"n/a - mixes {r['distinct']} models"
            for col, val in enumerate((r["barcode"], r["model"], tier, note)):
                table.setItem(row, col, QTableWidgetItem(str(val)))
        table.resizeColumnsToContents()
        lay.addWidget(table)
        buttons = QDialogButtonBox(QDialogButtonBox.Close, dlg)
        buttons.rejected.connect(dlg.reject)
        buttons.accepted.connect(dlg.accept)
        lay.addWidget(buttons)
        dlg.exec_()

    # Coverage & Degeneracy

    def _create_coverage_group(self):
        group = QGroupBox("Coverage and Degeneracy Settings")
        layout = QFormLayout()
        layout.setSpacing(12)
        layout.setVerticalSpacing(18)
        layout.setLabelAlignment(Qt.AlignLeft)
        layout.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)

        self.min_coverage_spin = QSpinBox()
        self.min_coverage_spin.setRange(1, 1000)
        self.min_coverage_spin.setValue(100)
        self.min_coverage_spin.setToolTip("Minimum coverage threshold for consensus calling")
        cov_label = QLabel("Minimum Coverage Threshold:")
        cov_label.setStyleSheet("color: #64748b; font-size: 14px;")
        cov_label.setMinimumWidth(180)
        layout.addRow(cov_label, self.min_coverage_spin)

        self.degeneracy_threshold_spin = QSpinBox()
        self.degeneracy_threshold_spin.setRange(1, 100)
        self.degeneracy_threshold_spin.setValue(20)
        self.degeneracy_threshold_spin.setSingleStep(1)
        self.degeneracy_threshold_spin.setSuffix("%")
        self.degeneracy_threshold_spin.setToolTip("Percentage threshold for determining base frequencies (1-100%)")
        deg_label = QLabel("Degeneracy Threshold / δ (%):")
        deg_label.setStyleSheet("color: #64748b; font-size: 14px;")
        deg_label.setMinimumWidth(180)
        layout.addRow(deg_label, self.degeneracy_threshold_spin)

        group.setLayout(layout)
        return group

    # Ploidy

    def _create_ploidy_group(self):
        group = QGroupBox("Ploidy Settings")
        layout = QFormLayout()
        layout.setSpacing(12)
        layout.setVerticalSpacing(18)
        layout.setLabelAlignment(Qt.AlignLeft)
        layout.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)

        self.ploidy_spin = QSpinBox()
        self.ploidy_spin.setRange(1, 10)
        self.ploidy_spin.setValue(2)
        self.ploidy_spin.setToolTip("Haploid = 1, Diploid = 2, etc.")
        ploidy_label = QLabel("Ploidy:")
        ploidy_label.setStyleSheet("color: #64748b; font-size: 14px;")
        ploidy_label.setMinimumWidth(180)
        layout.addRow(ploidy_label, self.ploidy_spin)

        info = QLabel("Haploid = 1, Diploid = 2, Polyploid = 3+")
        info.setStyleSheet("color: #64748b; font-style: italic; font-size: 14px;")
        layout.addRow("", info)

        group.setLayout(layout)
        return group

    # Indel Rules

    def _create_indel_group(self):
        group = QGroupBox("Indel Rules")
        layout = QVBoxLayout()

        self.indel_rules_combo = QComboBox()
        # Index order is load-bearing: 0/1/2 map to equal_or_more / more_than /
        # custom_percentage on save, and _on_indel_rules_changed keys on index 2.
        self.indel_rules_combo.addItems([
            "Half the reads or more (IMF >= 0.50)",
            "More than half the reads (IMF > 0.50)",
            "Custom fraction of reads",
        ])
        self.indel_rules_combo.setToolTip(
            "How much read support an indel needs before it may edit the consensus.\n\n"
            "Judged on IMF, the fraction of reads supporting the indel, which bcftools "
            "mpileup computes before the caller runs - so the rule behaves identically "
            "under Call Mode c and m.\n\n"
            "This is one of three conditions. An indel is applied only when read depth "
            "also meets Min Coverage AND the indel does not break a reading frame. The "
            "frame test is always on and has no control here; indels within 12 nt are "
            "judged as a group, so a -1 nt and a +1 nt close together are recognised as "
            "cancelling rather than rejected individually.\n\n"
            "On hac basecalls no indel reaches this rule at all: the hac mpileup profile "
            "carries -I, so bcftools calls no indels. Deletion evidence is still listed "
            "in the diagnostic log under INDEL EVIDENCE (not acted upon)."
        )
        self.indel_rules_combo.currentIndexChanged.connect(self._on_indel_rules_changed)
        layout.addWidget(self.indel_rules_combo)

        custom_layout = QHBoxLayout()
        custom_layout.addWidget(QLabel("Custom percentage of reads:"))
        self.indel_custom_spin = QDoubleSpinBox()
        self.indel_custom_spin.setRange(1.0, 100.0)
        self.indel_custom_spin.setValue(50.0)
        self.indel_custom_spin.setSuffix("%")
        self.indel_custom_spin.setEnabled(False)
        custom_layout.addWidget(self.indel_custom_spin)
        custom_layout.addStretch()
        layout.addLayout(custom_layout)

        group.setLayout(layout)
        return group

    def _on_indel_rules_changed(self):
        self.indel_custom_spin.setEnabled(self.indel_rules_combo.currentIndex() == 2)

    def _on_auto_base_quality_changed(self):
        auto = self.auto_base_quality_check.isChecked()
        self.min_base_quality_spin.setEnabled(not auto)
        self.max_base_quality_spin.setEnabled(not auto)
        if auto:
            forced = getattr(self, "force_sup_check", None)
            tiers = {"sup"} if (forced and forced.isChecked()) else \
                {r["tier"] for r in self._detection}
            if tiers == {"sup"}:
                self.min_base_quality_spin.setValue(1)
                self.max_base_quality_spin.setValue(35)
            elif tiers and "sup" not in tiers:
                self.min_base_quality_spin.setValue(5)
                self.max_base_quality_spin.setValue(30)
        self._update_basecall_warning()

    def _sync_filter(self, source):
        if source == "general" and self.filter_general_radio.isChecked():
            self.filter_influenza_radio.setChecked(False)
        elif source == "influenza" and self.filter_influenza_radio.isChecked():
            self.filter_general_radio.setChecked(False)
        if not self.filter_general_radio.isChecked() and not self.filter_influenza_radio.isChecked():
            self.filter_general_radio.setChecked(True)

    # Variant Call Settings

    def _create_variant_group(self):
        group = QGroupBox("Variant Call Settings")
        layout = QFormLayout()
        layout.setSpacing(12)
        layout.setVerticalSpacing(18)
        layout.setLabelAlignment(Qt.AlignLeft)
        layout.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)

        self.variant_depth_spin = QSpinBox()
        self.variant_depth_spin.setRange(1, 10000000)
        self.variant_depth_spin.setValue(10000)
        self.variant_depth_spin.setToolTip("Depth per site for mpileup (-d parameter)")
        depth_label = QLabel("Depth per site:")
        depth_label.setStyleSheet("color: #64748b; font-size: 14px;")
        depth_label.setMinimumWidth(180)
        layout.addRow(depth_label, self.variant_depth_spin)

        self.min_base_quality_spin = QSpinBox()
        self.min_base_quality_spin.setRange(0, 60)
        self.min_base_quality_spin.setValue(5)
        self.min_base_quality_spin.setToolTip(
            "Minimum base quality (-Q) for bcftools mpileup. Omit this key from the "
            "config file to take the basecall-tier default: 5 for hac (paired with "
            "--max-BQ 30) or 1 for sup (paired with --max-BQ 35), matching bcftools' "
            "ont and ont-sup profiles.\n\n"
            "The refinement pileup floors at 5 regardless. bcftools admits low-quality "
            "bases but down-weights them via --max-BQ; the refinement pileup counts "
            "every base at equal weight and has no equivalent, so following sup's -Q1 "
            "would make it more permissive than bcftools, not equivalent."
        )
        min_bq_label = QLabel("Min base quality:")
        min_bq_label.setStyleSheet("color: #64748b; font-size: 14px;")
        min_bq_label.setMinimumWidth(180)
        layout.addRow(min_bq_label, self.min_base_quality_spin)

        self.max_base_quality_spin = QSpinBox()
        self.max_base_quality_spin.setRange(0, 93)
        self.max_base_quality_spin.setValue(30)
        self.max_base_quality_spin.setToolTip(
            "Maximum base quality (--max-BQ) for bcftools mpileup. ONT reports "
            "overconfident high-Q values; this caps them so a low -Q floor stays safe.\n\n"
            "Paired with Min base quality: bcftools ships 1/35 for sup and 5/30 for hac. "
            "Leave Auto on to keep the pair together."
        )
        max_bq_label = QLabel("Max base quality:")
        max_bq_label.setStyleSheet("color: #64748b; font-size: 14px;")
        max_bq_label.setMinimumWidth(180)
        layout.addRow(max_bq_label, self.max_base_quality_spin)

        # One checkbox for both: -Q and --max-BQ are a validated pair, and the
        # failure this replaces was them silently coming apart. When checked, both
        # keys are omitted from the config so the shell resolves them per tier.
        self.auto_base_quality_check = ToggleSwitch("Auto (tier default)")
        self.auto_base_quality_check.setChecked(True)
        self.auto_base_quality_check.setToolTip(
            "Take both base-quality values from the detected basecall tier: 1/35 for "
            "sup, 5/30 for hac, matching bcftools' ont and ont-sup profiles.\n\n"
            "Unchecking pins both values, which is passed to bcftools unchanged. Note "
            "the refinement pileup floors at 5 regardless: bcftools admits low-quality "
            "bases but down-weights them via --max-BQ, and the refinement pileup counts "
            "every base at equal weight with no equivalent."
        )
        self.auto_base_quality_check.toggled.connect(self._on_auto_base_quality_changed)
        layout.addRow(QLabel(""), self.auto_base_quality_check)

        self.variant_mode_combo = QComboBox()
        self.variant_mode_combo.addItems([
            "Multiallelic Caller (-m: alternative)",
            "Consensus Caller (-c: default)",
        ])
        self.variant_mode_combo.setCurrentIndex(1)
        self.variant_mode_combo.setToolTip(
            "-c (Consensus Caller): vcfutils.pl vcf2fq pipeline - biallelic calls, "
            "N-masking by padding uncovered positions. This is the default and the path "
            "the pipeline's validation covers.\n\n"
            "-m (Multiallelic Caller): bcftools consensus pipeline - handles genuine "
            "tri-allelic sites, N-masking via a samtools depth coverage map. It draws "
            "ambiguity codes from genotypes rather than from vcf2fq, so it produces a "
            "different set of degenerate sites. Not yet covered by the pipeline's "
            "validation - measure before relying on it."
        )
        mode_label = QLabel("Call mode:")
        mode_label.setStyleSheet("color: #64748b; font-size: 14px;")
        mode_label.setMinimumWidth(180)
        layout.addRow(mode_label, self.variant_mode_combo)

        group.setLayout(layout)
        return group

    # Filter Mode

    def _create_filter_group(self):
        group = QGroupBox("Filter Mode")
        layout = QVBoxLayout()
        layout.setSpacing(10)

        self.filter_general_radio = QCheckBox("General Consensus (No gene filtering)")
        self.filter_general_radio.setStyleSheet("color: #64748b; font-size: 14px;")
        self.filter_general_radio.setChecked(True)
        self.filter_general_radio.stateChanged.connect(lambda: self._sync_filter("general"))
        layout.addWidget(self.filter_general_radio)

        self.filter_influenza_radio = QCheckBox("Influenza Filter (HA*, NA*, PB2, PB1, PA, NP, MP, NS)")
        self.filter_influenza_radio.setStyleSheet("color: #64748b; font-size: 14px;")
        self.filter_influenza_radio.stateChanged.connect(lambda: self._sync_filter("influenza"))
        layout.addWidget(self.filter_influenza_radio)

        group.setLayout(layout)
        return group

    # Qualimap

    def _create_qualimap_group(self):
        group = QGroupBox("Qualimap BAM QC Settings")
        layout = QFormLayout()
        layout.setSpacing(12)
        layout.setVerticalSpacing(18)
        layout.setLabelAlignment(Qt.AlignLeft)
        layout.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)

        self.qualimap_enabled_check = ToggleSwitch("Enable Qualimap BAM QC")
        self.qualimap_enabled_check.setChecked(True)
        self.qualimap_enabled_check.setToolTip("Enable/disable Qualimap BAM quality control")
        layout.addRow("", self.qualimap_enabled_check)

        info = QLabel(
            "Qualimap provides comprehensive BAM quality control reports "
            "including coverage analysis, mapping quality, and alignment statistics."
        )
        info.setStyleSheet("color: #64748b; font-style: italic; font-size: 14px;")
        info.setWordWrap(True)
        layout.addRow("", info)

        threading_info = QLabel("Threading: Auto-detects optimal thread count based on available CPU cores")
        threading_info.setStyleSheet("color: #059669; font-style: italic; font-size: 12px; font-weight: bold;")
        layout.addRow("", threading_info)

        group.setLayout(layout)
        return group

    # NanoPlot

    def _create_nanoplot_group(self):
        group = QGroupBox("NanoPlot Raw Read QC Settings")
        layout = QFormLayout()
        layout.setSpacing(12)
        layout.setVerticalSpacing(18)
        layout.setLabelAlignment(Qt.AlignLeft)
        layout.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)

        self.nanoplot_enabled_check = ToggleSwitch("Enable NanoPlot Raw Reads QC")
        self.nanoplot_enabled_check.setChecked(True)
        self.nanoplot_enabled_check.setToolTip(
            "Run NanoPlot on raw ONT reads (fastq.gz) before adapter trimming.\n"
            "Produces per-barcode HTML QC reports in results/step_1_raw_read_qc_nanoplot/"
        )
        layout.addRow("", self.nanoplot_enabled_check)

        info = QLabel(
            "NanoPlot produces ONT-specific QC metrics: read length distribution, "
            "quality scores, N50, and total bases - using raw reads before any processing."
        )
        info.setStyleSheet("color: #64748b; font-style: italic; font-size: 14px;")
        info.setWordWrap(True)
        layout.addRow("", info)

        output_info = QLabel("Output: results/step_1_raw_read_qc_nanoplot/barcode*/NanoPlot-report.html")
        output_info.setStyleSheet("color: #059669; font-style: italic; font-size: 12px; font-weight: bold;")
        layout.addRow("", output_info)

        group.setLayout(layout)
        return group

    # Parallel Processing

    def _create_parallel_group(self):
        group = QGroupBox("Parallel Processing")
        layout = QFormLayout()
        layout.setSpacing(12)
        layout.setVerticalSpacing(18)
        layout.setLabelAlignment(Qt.AlignLeft)
        layout.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)

        cpu_count = os.cpu_count() or 1

        self.parallel_enabled_check = ToggleSwitch("Enable parallel barcode processing")
        self.parallel_enabled_check.setChecked(True)
        self.parallel_enabled_check.setToolTip(
            "Process multiple barcodes simultaneously. Disable for sequential (single-threaded) processing."
        )
        self.parallel_enabled_check.stateChanged.connect(self._on_parallel_toggled)
        layout.addRow("", self.parallel_enabled_check)

        self.parallel_threads_spin = QSpinBox()
        self.parallel_threads_spin.setRange(1, cpu_count)
        self.parallel_threads_spin.setValue(cpu_count)
        self.parallel_threads_spin.setToolTip(
            "Number of barcodes to process in parallel (max: available CPU cores)"
        )
        threads_label = QLabel("Threads:")
        threads_label.setStyleSheet("color: #64748b; font-size: 14px;")
        threads_label.setMinimumWidth(180)
        layout.addRow(threads_label, self.parallel_threads_spin)

        self.parallel_info_label = QLabel(f"Detected {cpu_count} CPU cores")
        self.parallel_info_label.setStyleSheet(
            "color: #059669; font-style: italic; font-size: 12px; font-weight: bold;"
        )
        layout.addRow("", self.parallel_info_label)

        group.setLayout(layout)
        return group

    def _on_parallel_toggled(self):
        enabled = self.parallel_enabled_check.isChecked()
        self.parallel_threads_spin.setEnabled(enabled)

    # Advanced Criteria

    def _create_advanced_group(self):
        group = QGroupBox("Advanced Criteria Settings")
        layout = QFormLayout()
        layout.setSpacing(12)
        layout.setVerticalSpacing(18)
        layout.setLabelAlignment(Qt.AlignLeft)
        layout.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)

        # Strand Bias
        self.strand_balance_spin = QDoubleSpinBox()
        self.strand_balance_spin.setRange(0.0, 1.0)
        self.strand_balance_spin.setValue(0.1)
        self.strand_balance_spin.setSingleStep(0.05)
        self.strand_balance_spin.setDecimals(2)
        self.strand_balance_spin.setToolTip("Warn if strand balance (min/max of fwd/rev) falls below this value (0-1)")
        sb_label = QLabel("Minimum Strand Balance Threshold:")
        sb_label.setStyleSheet("color: #64748b; font-size: 14px;")
        sb_label.setMinimumWidth(180)
        layout.addRow(sb_label, self.strand_balance_spin)

        self.strict_strand_bias_check = ToggleSwitch("Strict: strand bias warnings override base calls")
        self.strict_strand_bias_check.setToolTip(
            "When enabled, sites flagged for strand bias are kept as ambiguous instead of resolved"
        )
        layout.addRow("", self.strict_strand_bias_check)

        # Homopolymer
        self.homopolymer_min_length_spin = QSpinBox()
        self.homopolymer_min_length_spin.setRange(2, 20)
        self.homopolymer_min_length_spin.setValue(5)
        self.homopolymer_min_length_spin.setToolTip("Minimum run length to flag as homopolymer")
        hp_len_label = QLabel("Homopolymer Min Length:")
        hp_len_label.setStyleSheet("color: #64748b; font-size: 14px;")
        hp_len_label.setMinimumWidth(180)
        layout.addRow(hp_len_label, self.homopolymer_min_length_spin)

        self.homopolymer_window_spin = QSpinBox()
        self.homopolymer_window_spin.setRange(1, 50)
        self.homopolymer_window_spin.setValue(5)
        self.homopolymer_window_spin.setToolTip("Window size (bp) around each site to search for homopolymers")
        hp_win_label = QLabel("Homopolymer Window:")
        hp_win_label.setStyleSheet("color: #64748b; font-size: 14px;")
        hp_win_label.setMinimumWidth(180)
        layout.addRow(hp_win_label, self.homopolymer_window_spin)

        self.strict_homopolymer_check = ToggleSwitch("Strict: homopolymer warnings override base calls")
        self.strict_homopolymer_check.setToolTip(
            "When enabled, sites near homopolymers are kept as ambiguous instead of resolved"
        )
        layout.addRow("", self.strict_homopolymer_check)

        # Read-End Enrichment
        self.read_end_threshold_spin = QDoubleSpinBox()
        self.read_end_threshold_spin.setRange(0.0, 1.0)
        self.read_end_threshold_spin.setValue(0.8)
        self.read_end_threshold_spin.setSingleStep(0.05)
        self.read_end_threshold_spin.setDecimals(2)
        self.read_end_threshold_spin.setToolTip(
            "Warn if fraction of ALT reads from read edges exceeds this value (0-1)"
        )
        re_label = QLabel("Maximum Read-End Enrichment Threshold:")
        re_label.setStyleSheet("color: #64748b; font-size: 14px;")
        re_label.setMinimumWidth(180)
        layout.addRow(re_label, self.read_end_threshold_spin)

        self.read_end_edge_fraction_spin = QSpinBox()
        self.read_end_edge_fraction_spin.setRange(1, 50)
        self.read_end_edge_fraction_spin.setValue(10)
        self.read_end_edge_fraction_spin.setSingleStep(1)
        self.read_end_edge_fraction_spin.setSuffix("%")
        self.read_end_edge_fraction_spin.setToolTip("Percentage of each read end considered 'edge' (1-50%)")
        ref_label = QLabel("Read-End Edge Fraction (%):")
        ref_label.setStyleSheet("color: #64748b; font-size: 14px;")
        ref_label.setMinimumWidth(180)
        layout.addRow(ref_label, self.read_end_edge_fraction_spin)

        self.strict_read_end_check = ToggleSwitch("Strict: read-end enrichment warnings override base calls")
        self.strict_read_end_check.setToolTip(
            "When enabled, sites with read-end enrichment are kept as ambiguous instead of resolved"
        )
        layout.addRow("", self.strict_read_end_check)

        group.setLayout(layout)
        return group

    # Config Management Buttons

    def _create_config_buttons_group(self):
        group = QGroupBox("Configuration Management")
        layout = QHBoxLayout()
        layout.setSpacing(15)

        save_btn = QPushButton("Save Configuration")
        save_btn.clicked.connect(self.save_configuration)
        save_btn.setMinimumHeight(40)
        save_btn.setMinimumWidth(160)
        layout.addWidget(save_btn)

        load_btn = QPushButton("Load Configuration")
        load_btn.clicked.connect(self.load_configuration)
        load_btn.setMinimumHeight(40)
        load_btn.setMinimumWidth(160)
        layout.addWidget(load_btn)

        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.clicked.connect(self.reset_configuration)
        reset_btn.setMinimumHeight(40)
        reset_btn.setMinimumWidth(160)
        layout.addWidget(reset_btn)

        group.setLayout(layout)
        return group

    # Public API

    def get_configuration(self):
        indel_rules_map = {0: "equal_or_more", 1: "more_than", 2: "custom_percentage"}
        variant_mode = "m" if self.variant_mode_combo.currentIndex() == 0 else "c"
        filter_mode = "influenza" if self.filter_influenza_radio.isChecked() else "general"
        auto_bq = self.auto_base_quality_check.isChecked()

        return {
            "min_coverage": self.min_coverage_spin.value(),
            "degeneracy_threshold": self.degeneracy_threshold_spin.value(),
            "ploidy": self.ploidy_spin.value(),
            "indel_rules": indel_rules_map[self.indel_rules_combo.currentIndex()],
            "indel_custom_percentage": self.indel_custom_spin.value(),
            "variant_call_depth": self.variant_depth_spin.value(),
            # None means "omit the key", which is how auto reaches the shell.
            "min_base_quality": None if auto_bq else self.min_base_quality_spin.value(),
            "max_base_quality": None if auto_bq else self.max_base_quality_spin.value(),
            "force_sup_profile": self.force_sup_check.isChecked(),
            "variant_call_mode": variant_mode,
            "filter_mode": filter_mode,
            "qualimap_enabled": self.qualimap_enabled_check.isChecked(),
            "nanoplot_enabled": self.nanoplot_enabled_check.isChecked(),
            "strand_balance_threshold": self.strand_balance_spin.value(),
            "homopolymer_min_length": self.homopolymer_min_length_spin.value(),
            "homopolymer_window": self.homopolymer_window_spin.value(),
            "read_end_threshold": self.read_end_threshold_spin.value(),
            "read_end_edge_fraction": self.read_end_edge_fraction_spin.value() / 100.0,
            "strict_strand_bias": self.strict_strand_bias_check.isChecked(),
            "strict_homopolymer": self.strict_homopolymer_check.isChecked(),
            "strict_read_end": self.strict_read_end_check.isChecked(),
            "parallel_enabled": self.parallel_enabled_check.isChecked(),
            "parallel_threads": self.parallel_threads_spin.value(),
        }

    @staticmethod
    def _flatten_config(config):
        """Accept either config schema and return the flat one this tab's widgets use.

        Two schemas are in circulation and BOTH are written by this project: the flat form
        this tab saves (ont_analyzer_config.json) and the nested form the pipeline worker
        writes on every run and ships as the documented template (pipeline_config.json).
        Load Configuration previously understood only the flat form, so opening the
        application's own generated config applied three widgets and then raised
        TypeError: unhashable type: 'dict' - leaving the dialog half-populated with a mix
        of file values and stale ones, which is worse than either.
        """
        if not isinstance(config, dict):
            return {}
        flat = {k: v for k, v in config.items() if not isinstance(v, dict)}
        nested = config.get("indel_rules")
        if isinstance(nested, dict):
            # Nested schema stores a rule per direction; this tab has a single control, so
            # take insertions as the representative and note when deletions disagree.
            flat["indel_rules"] = nested.get("insertions", nested.get("deletions", "equal_or_more"))
            flat["_indel_rules_split"] = (
                nested.get("insertions") != nested.get("deletions")
                and nested.get("deletions") is not None)
            if "custom_percentage" in nested:
                flat["indel_custom_percentage"] = nested["custom_percentage"]
        for src, dst in (("variant_call_settings", {"call_mode": "variant_call_mode",
                                                    "depth_per_site": "variant_call_depth",
                                                    "min_base_quality": "min_base_quality",
                                                    "max_base_quality": "max_base_quality"}),
                         ("advanced_criteria", None),
                         ("parallel", {"enabled": "parallel_enabled",
                                       "threads": "parallel_threads"}),
                         ("qualimap", {"enabled": "qualimap_enabled"}),
                         ("nanoplot", {"enabled": "nanoplot_enabled"})):
            block = config.get(src)
            if not isinstance(block, dict):
                continue
            for k, v in block.items():
                if isinstance(v, dict):
                    continue
                flat.setdefault(dst[k] if dst and k in dst else k, v)
        return flat

    def apply_configuration(self, config):
        config = self._flatten_config(config)

        self.min_coverage_spin.setValue(int(config.get("min_coverage", 100)))

        _deg = config.get("degeneracy_threshold", 20)
        try:
            _deg_val = float(_deg)
        except Exception:
            _deg_val = 20.0
        # Only a strict fraction (0 < v < 1) is the legacy 0-1 form. The old test `<= 1.0`
        # also caught a literal 1, so a saved threshold of 1% reloaded as 100% - silently
        # inverting the rule from "resolve almost everything" to "resolve almost nothing".
        if 0.0 < _deg_val < 1.0:
            _deg_val = _deg_val * 100.0
        _lo, _hi = self.degeneracy_threshold_spin.minimum(), self.degeneracy_threshold_spin.maximum()
        self.degeneracy_threshold_spin.setValue(max(_lo, min(_hi, int(round(_deg_val)))))

        self.ploidy_spin.setValue(int(config.get("ploidy", 2)))

        indel_rules = config.get("indel_rules", "equal_or_more")
        if not isinstance(indel_rules, str):
            indel_rules = "equal_or_more"
        idx = {"equal_or_more": 0, "more_than": 1, "custom_percentage": 2}.get(indel_rules, 0)
        self.indel_rules_combo.setCurrentIndex(idx)
        self._on_indel_rules_changed()
        self.indel_custom_spin.setValue(float(config.get("indel_custom_percentage", 50.0)))

        self.variant_depth_spin.setValue(int(config.get("variant_call_depth", 10000)))
        # A missing or null value is auto; only an explicit number pins the pair.
        min_bq = config.get("min_base_quality")
        max_bq = config.get("max_base_quality")
        self.auto_base_quality_check.setChecked(min_bq is None)
        self.min_base_quality_spin.setValue(5 if min_bq is None else min_bq)
        self.max_base_quality_spin.setValue(30 if max_bq is None else max_bq)
        self.force_sup_check.setChecked(bool(config.get("force_sup_profile", False)))
        self._on_auto_base_quality_changed()
        self.variant_mode_combo.setCurrentIndex(0 if config.get("variant_call_mode", "c") == "m" else 1)

        if config.get("filter_mode", "general") == "influenza":
            self.filter_influenza_radio.setChecked(True)
        else:
            self.filter_general_radio.setChecked(True)

        self.qualimap_enabled_check.setChecked(config.get("qualimap_enabled", True))
        self.nanoplot_enabled_check.setChecked(config.get("nanoplot_enabled", True))

        self.strand_balance_spin.setValue(float(config.get("strand_balance_threshold", 0.1)))
        self.homopolymer_min_length_spin.setValue(int(config.get("homopolymer_min_length", 5)))
        self.homopolymer_window_spin.setValue(int(config.get("homopolymer_window", 5)))
        self.read_end_threshold_spin.setValue(float(config.get("read_end_threshold", 0.8)))
        _ref = config.get("read_end_edge_fraction", 0.1)
        self.read_end_edge_fraction_spin.setValue(int(round(_ref * 100)) if _ref <= 1.0 else int(_ref))
        self.strict_strand_bias_check.setChecked(config.get("strict_strand_bias", False))
        self.strict_homopolymer_check.setChecked(config.get("strict_homopolymer", False))
        self.strict_read_end_check.setChecked(config.get("strict_read_end", False))
        self.parallel_enabled_check.setChecked(config.get("parallel_enabled", True))
        self.parallel_threads_spin.setValue(int(config.get("parallel_threads", os.cpu_count() or 1)))
        self._on_parallel_toggled()

    def save_configuration(self):
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save Configuration", "ont_analyzer_config.json",
            "JSON Files (*.json);;All Files (*)"
        )
        if filename:
            try:
                config = self.get_configuration()
                with open(filename, "w") as f:
                    json.dump(config, f, indent=2)
                self.parent_window.append_log(f"Configuration saved to: {filename}")
            except Exception as e:
                QMessageBox.critical(self, "Save Error", f"Failed to save configuration: {e}")

    def load_configuration(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Load Configuration", "", "JSON Files (*.json);;All Files (*)"
        )
        if filename:
            try:
                with open(filename, "r") as f:
                    config = json.load(f)
                self.apply_configuration(config)
                self.parent_window.append_log(f"Configuration loaded from: {filename}")
            except Exception as e:
                QMessageBox.critical(self, "Load Error", f"Failed to load configuration: {e}")

    def reset_configuration(self):
        reply = QMessageBox.question(
            self, "Reset Configuration",
            "Are you sure you want to reset all configuration values to defaults?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.min_coverage_spin.setValue(100)
            self.degeneracy_threshold_spin.setValue(20)
            self.ploidy_spin.setValue(2)
            self.indel_rules_combo.setCurrentIndex(0)
            self.indel_custom_spin.setValue(50.0)
            self.variant_depth_spin.setValue(10000)
            self.variant_mode_combo.setCurrentIndex(1)
            self.auto_base_quality_check.setChecked(True)
            self.min_base_quality_spin.setValue(5)
            self.max_base_quality_spin.setValue(30)
            self.force_sup_check.setChecked(False)
            self._on_auto_base_quality_changed()
            self.filter_general_radio.setChecked(True)
            self.filter_influenza_radio.setChecked(False)
            self.qualimap_enabled_check.setChecked(True)
            self.nanoplot_enabled_check.setChecked(True)
            self.strand_balance_spin.setValue(0.1)
            self.homopolymer_min_length_spin.setValue(5)
            self.homopolymer_window_spin.setValue(5)
            self.read_end_threshold_spin.setValue(0.8)
            self.read_end_edge_fraction_spin.setValue(10)
            self.strict_strand_bias_check.setChecked(False)
            self.strict_homopolymer_check.setChecked(False)
            self.strict_read_end_check.setChecked(False)
            self.parallel_enabled_check.setChecked(True)
            self.parallel_threads_spin.setValue(os.cpu_count() or 1)
            self._on_parallel_toggled()
            self.parent_window.append_log("Configuration reset to defaults")

