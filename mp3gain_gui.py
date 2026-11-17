#!/usr/bin/env python3
"""Simple Qt GUI for recursively analyzing and adjusting MP3 files."""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


REFERENCE_VOLUME_DB = 89.0


@dataclass
class Track:
    path: str
    volume: float | None = None
    clipping: str = "—"
    gain: float | None = None


def find_mp3gain() -> str | None:
    local_binary = Path(__file__).with_name("mp3gain")
    if local_binary.is_file() and os.access(local_binary, os.X_OK):
        return str(local_binary)
    return shutil.which("mp3gain")


def find_mp3_files(folder: str) -> list[str]:
    return sorted(
        str(path)
        for path in Path(folder).rglob("*")
        if path.is_file() and path.suffix.lower() == ".mp3"
    )


def parse_analysis(output: str, path: str, desired_db: float) -> Track:
    for line in output.splitlines():
        if not line or line.startswith("File\t"):
            continue
        fields = line.split("\t")
        if len(fields) < 4:
            continue
        try:
            recommended_change = float(fields[2])
            max_amplitude = float(fields[3])
        except ValueError:
            continue

        current_volume = REFERENCE_VOLUME_DB - recommended_change
        gain = desired_db - current_volume
        clipped = max_amplitude * math.pow(2.0, gain / 6.020599913) > 32767.0
        return Track(path, current_volume, "Yes" if clipped else "No", gain)
    raise RuntimeError(f"No analysis data returned for {path}")


class Mp3GainWorker(QObject):
    progress = Signal(int, int)
    tracks_ready = Signal(object)
    finished = Signal()
    failed = Signal(str)

    def __init__(self, executable: str, paths: list[str], desired_db: float, apply: bool):
        super().__init__()
        self.executable = executable
        self.paths = paths
        self.desired_db = desired_db
        self.apply = apply

    @Slot()
    def run(self) -> None:
        analyzed_tracks: list[Track] = []
        try:
            for index, path in enumerate(self.paths, start=1):
                if self.apply:
                    self._apply_gain(path)
                result = self._run_analysis(path)
                analyzed_tracks.append(parse_analysis(result.stdout, path, self.desired_db))
                self.progress.emit(index, len(self.paths))
            self.tracks_ready.emit(analyzed_tracks)
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            self.failed.emit(str(error))
        finally:
            self.finished.emit()

    def _run_analysis(self, path: str) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [self.executable, "-o", "-e", path],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            details = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"Analysis failed for {path}: {details}")
        return result

    def _apply_gain(self, path: str) -> None:
        offset = self.desired_db - REFERENCE_VOLUME_DB
        result = subprocess.run(
            [self.executable, "-r", "-d", f"{offset:.3f}", "-c", "-e", path],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            details = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"Could not apply gain to {path}: {details}")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MP3Gain")
        self.resize(1100, 650)

        self.executable = find_mp3gain()
        self.folder: str | None = None
        self.tracks: dict[str, Track] = {}
        self.thread: QThread | None = None
        self.worker: Mp3GainWorker | None = None

        self.select_button = QPushButton("Select Folder")
        self.select_button.clicked.connect(self.select_folder)
        self.gain_input = QLineEdit("92")
        self.gain_input.setMaximumWidth(110)
        self.gain_input.setPlaceholderText("dB")
        self.analyze_button = QPushButton("Analyze All")
        self.analyze_button.clicked.connect(self.analyze)
        self.apply_button = QPushButton("Apply")
        self.apply_button.clicked.connect(self.apply_gain)
        self.status = QLabel("Select a folder containing MP3 files.")
        self.progress = QProgressBar()
        self.progress.setVisible(False)

        controls = QHBoxLayout()
        controls.addWidget(self.select_button)
        controls.addWidget(QLabel("Desired volume (dB):"))
        controls.addWidget(self.gain_input)
        controls.addWidget(self.analyze_button)
        controls.addWidget(self.apply_button)
        controls.addStretch()

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Absolute path", "Volume (dB)", "Clipping", "Gain (dB)"])
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, self.table.horizontalHeader().ResizeMode.Stretch)

        layout = QVBoxLayout()
        layout.addLayout(controls)
        layout.addWidget(self.table)
        layout.addWidget(self.progress)
        layout.addWidget(self.status)

        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)
        self._set_enabled(True)

    def select_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select MP3 folder")
        if not folder:
            return
        self.folder = folder
        self.tracks.clear()
        self.table.setRowCount(0)
        paths = find_mp3_files(folder)
        for path in paths:
            self.tracks[path] = Track(path)
        self._refresh_table()
        self._set_enabled(True)
        self.status.setText(f"{len(paths)} MP3 file(s) found in {folder}")

    def analyze(self) -> None:
        self._start_worker(False)

    def apply_gain(self) -> None:
        self._start_worker(True)

    def _start_worker(self, apply: bool) -> None:
        if not self.executable:
            QMessageBox.critical(self, "mp3gain not found", "Build mp3gain first or put it on PATH.")
            return
        if not self.tracks:
            QMessageBox.information(self, "No MP3 files", "Select a folder containing MP3 files first.")
            return
        try:
            desired_db = float(self.gain_input.text())
        except ValueError:
            QMessageBox.warning(self, "Invalid gain", "Desired gain must be a number in dB.")
            return
        if not -100.0 < desired_db < 200.0:
            QMessageBox.warning(self, "Invalid gain", "Desired gain must be between -100 and 200 dB.")
            return

        self._set_enabled(False)
        self.progress.setValue(0)
        self.progress.setMaximum(len(self.tracks))
        self.progress.setVisible(True)
        self.status.setText("Applying gain and refreshing analysis..." if apply else "Analyzing tracks...")

        self.thread = QThread(self)
        self.worker = Mp3GainWorker(find_mp3gain() or "mp3gain", list(self.tracks), desired_db, apply)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._update_progress)
        self.worker.tracks_ready.connect(self._receive_tracks)
        self.worker.failed.connect(self._worker_failed)
        self.worker.finished.connect(self._worker_finished)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self._thread_finished)
        self.thread.start()

    @Slot(object)
    def _receive_tracks(self, tracks: list[Track]) -> None:
        self.tracks = {track.path: track for track in tracks}
        self._refresh_table()

    @Slot(int, int)
    def _update_progress(self, current: int, total: int) -> None:
        self.progress.setMaximum(total)
        self.progress.setValue(current)

    @Slot(str)
    def _worker_failed(self, message: str) -> None:
        QMessageBox.critical(self, "mp3gain error", message)

    def _worker_finished(self) -> None:
        self.status.setText("Analysis complete." if self.worker and not self.worker.apply else "Gain applied and analysis refreshed.")

    def _thread_finished(self) -> None:
        self._set_enabled(True)
        self.progress.setVisible(False)
        self.worker = None
        self.thread = None

    def _refresh_table(self) -> None:
        self.table.setUpdatesEnabled(False)
        old_sorting = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.tracks))
        for row, track in enumerate(self.tracks.values()):
            values = (
                track.path,
                "—" if track.volume is None else f"{track.volume:.2f}",
                track.clipping,
                "—" if track.gain is None else f"{track.gain:+.2f}",
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.table.setSortingEnabled(old_sorting)
        self.table.setUpdatesEnabled(True)

    def _set_enabled(self, enabled: bool) -> None:
        self.select_button.setEnabled(enabled)
        self.analyze_button.setEnabled(enabled)
        analyzed = bool(self.tracks) and all(track.volume is not None for track in self.tracks.values())
        self.apply_button.setEnabled(enabled and analyzed)
        self.gain_input.setEnabled(enabled)


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(
        """
        QWidget { background: #25282d; color: #d7d9dc; }
        QPushButton { background: #3a3f46; border: 1px solid #555b64; padding: 6px 12px; border-radius: 4px; }
        QPushButton:hover { background: #454b54; }
        QPushButton:disabled { color: #777b82; background: #2d3035; }
        QLineEdit, QTableWidget { background: #30343a; border: 1px solid #505660; }
        QHeaderView::section { background: #363b42; color: #d7d9dc; padding: 5px; border: 0; }
        QTableWidget { gridline-color: #454a52; alternate-background-color: #2b2f35; }
        QProgressBar { border: 1px solid #505660; text-align: center; }
        QProgressBar::chunk { background: #657b8f; }
        """
    )
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
