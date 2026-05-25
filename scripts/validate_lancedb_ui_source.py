#!/usr/bin/env python
"""Native source-level UI smoke test for the local LanceDB desktop path.

This script exercises the real Settings and Search widgets plus the real
LanceDB workers. It is intended for native Windows source checkouts before the
packaged-app smoke gate.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
import time
import types
from pathlib import Path
from unittest.mock import MagicMock, patch


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# SearchTab displays source paths in column 2:
# ["Score", "Type", "Source", "Chunk", "Content Preview"].
SEARCH_RESULTS_SOURCE_COLUMN = 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    default_work_dir = (
        Path.home()
        / ".codex"
        / "validation"
        / "PGVectorRAGIndexer"
        / "lancedb-ui-smoke"
    )
    parser.add_argument("--work-dir", type=Path, default=default_work_dir)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--keep-work-dir", action="store_true")
    return parser.parse_args(argv)


def write_corpus(corpus_dir: Path) -> None:
    corpus_dir.mkdir(parents=True, exist_ok=True)
    (corpus_dir / "ev6_service.txt").write_text(
        "Kia EV6 battery diagnostic note. "
        "The EV6 service workflow checks the 12V battery, charging state, and diagnostic codes.\n",
        encoding="utf-8",
    )
    (corpus_dir / "banana_recipe.md").write_text(
        "# Banana Recipe\n\nMash bananas, add flour, bake until golden.\n",
        encoding="utf-8",
    )


def wait_for_qt(app, predicate, *, timeout_seconds: float, label: str) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            app.processEvents()
            return
        time.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for {label}")


def install_qtawesome_fallback() -> None:
    try:
        import qtawesome  # noqa: F401
    except ModuleNotFoundError:
        from PySide6.QtGui import QIcon

        sys.modules["qtawesome"] = types.SimpleNamespace(
            icon=lambda *args, **kwargs: QIcon()
        )


def run_smoke(args: argparse.Namespace) -> dict:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    work_dir = args.work_dir.resolve()
    if work_dir.exists() and not args.keep_work_dir:
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    appdata_dir = work_dir / "appdata"
    corpus_dir = work_dir / "corpus"
    db_path = work_dir / "lancedb_index"
    os.environ["APPDATA"] = str(appdata_dir)
    write_corpus(corpus_dir)

    from PySide6.QtWidgets import QApplication, QMessageBox

    install_qtawesome_fallback()

    from desktop_app.ui.search_tab import SearchTab
    from desktop_app.ui.settings_tab import SettingsTab
    from desktop_app.ui.workers import (
        clear_lancedb_access_locks,
        clear_lancedb_embedder_cache,
    )
    from desktop_app.utils import app_config

    clear_lancedb_access_locks()
    clear_lancedb_embedder_cache()
    app_config.set_local_lancedb_db_path(db_path)
    app_config.set_local_lancedb_search_enabled(False)
    app_config.clear_local_lancedb_index_metadata()

    app = QApplication.instance() or QApplication([])

    settings_tab = SettingsTab(docker_manager=MagicMock())
    settings_progress: list[str] = []
    original_ingest_progress = settings_tab._local_lancedb_ingest_progress

    def capture_ingest_progress(message: str) -> None:
        settings_progress.append(message)
        original_ingest_progress(message)

    settings_tab._local_lancedb_ingest_progress = capture_ingest_progress
    settings_tab._local_lancedb_search_checkbox.setChecked(True)

    failures: list[dict[str, str]] = []

    def capture_failure(parent, title, message):
        failures.append({"title": str(title), "message": str(message)})
        return QMessageBox.Ok

    ingest_started = time.perf_counter()
    with patch("desktop_app.ui.settings_tab.QMessageBox.critical", side_effect=capture_failure), patch(
        "desktop_app.ui.settings_tab.QFileDialog.getExistingDirectory",
        return_value=str(corpus_dir),
    ):
        settings_tab._build_local_lancedb_index()
        wait_for_qt(
            app,
            lambda: settings_tab._local_lancedb_ingest_worker
            and not settings_tab._local_lancedb_ingest_worker.isRunning(),
            timeout_seconds=args.timeout_seconds,
            label="local LanceDB index rebuild",
        )
    ingest_ms = (time.perf_counter() - ingest_started) * 1000
    if failures:
        raise AssertionError(f"Local index rebuild failed: {failures}")

    metadata = app_config.get_local_lancedb_index_metadata()
    if not metadata:
        raise AssertionError("Local LanceDB index metadata was not persisted")
    if Path(str(metadata.get("db_path"))) != db_path:
        raise AssertionError("Persisted local index metadata has the wrong db_path")
    if int(metadata.get("indexed_documents", 0)) != 2:
        raise AssertionError(f"Expected 2 indexed documents, got {metadata}")

    restarted_settings_tab = SettingsTab(docker_manager=MagicMock())
    restart_status = restarted_settings_tab._local_lancedb_status.text()
    if "Last indexed 2 documents" not in restart_status:
        raise AssertionError(f"Restart metadata status was not restored: {restart_status}")

    api_client = MagicMock()
    api_client.get_health.return_value = {"status": "ok"}
    search_tab = SearchTab(api_client, source_manager=MagicMock())
    search_tab.query_input.setText("EV6 battery diagnostic")
    search_tab.top_k_spin.setValue(3)
    search_progress: list[str] = []
    original_search_progress = search_tab._local_lancedb_search_progress

    def capture_search_progress(message: str) -> None:
        search_progress.append(message)
        original_search_progress(message)

    search_tab._local_lancedb_search_progress = capture_search_progress

    search_started = time.perf_counter()
    with patch("desktop_app.ui.search_tab.QMessageBox.critical", side_effect=capture_failure):
        search_tab.perform_search()
        wait_for_qt(
            app,
            lambda: search_tab.search_worker and not search_tab.search_worker.isRunning(),
            timeout_seconds=args.timeout_seconds,
            label="local LanceDB search",
        )
    search_ms = (time.perf_counter() - search_started) * 1000
    if failures:
        raise AssertionError(f"Local search failed: {failures}")

    result_files = [
        Path(search_tab.results_table.item(row, SEARCH_RESULTS_SOURCE_COLUMN).text()).name
        for row in range(search_tab.results_table.rowCount())
    ]
    if result_files[:1] != ["ev6_service.txt"]:
        raise AssertionError(f"Expected ev6_service.txt as top result, got {result_files}")
    if "Found 1 result (1 per file)" not in search_tab.status_label.text():
        raise AssertionError(f"Unexpected search status: {search_tab.status_label.text()}")

    warnings: list[dict[str, str]] = []

    def capture_warning(parent, title, message):
        warnings.append({"title": str(title), "message": str(message)})
        return QMessageBox.Ok

    app_config.clear_local_lancedb_index_metadata()
    with patch("desktop_app.ui.search_tab.QMessageBox.warning", side_effect=capture_warning):
        search_tab.perform_search()

    if not warnings or warnings[0]["title"] != "Local Index Not Built":
        raise AssertionError(f"Expected Local Index Not Built warning, got {warnings}")
    if "Rebuild Local Text/Markdown Index" not in warnings[0]["message"]:
        raise AssertionError(f"Warning does not point to the rebuild action: {warnings[0]}")

    return {
        "passed": True,
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "qt_platform": os.environ.get("QT_QPA_PLATFORM"),
        "work_dir": str(work_dir),
        "corpus_dir": str(corpus_dir),
        "db_path": str(db_path),
        "timings_ms": {
            "ingest": round(ingest_ms, 2),
            "search": round(search_ms, 2),
        },
        "settings": {
            "checkbox_text": settings_tab._local_lancedb_search_checkbox.text(),
            "rebuild_button_text": settings_tab._local_lancedb_index_btn.text(),
            "progress_messages": settings_progress,
            "status_after_ingest": settings_tab._local_lancedb_status.text(),
            "status_after_restart": restart_status,
        },
        "search": {
            "query": "EV6 battery diagnostic",
            "progress_messages": search_progress,
            "status": search_tab.status_label.text(),
            "result_files": result_files,
        },
        "warnings": warnings,
        "metadata": metadata,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = run_smoke(args)
    except Exception as exc:
        result = {"passed": False, "error": str(exc)}
        if args.output_json:
            args.output_json.parent.mkdir(parents=True, exist_ok=True)
            args.output_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        "PASS: local LanceDB source UI smoke "
        f"(ingest={result['timings_ms']['ingest']} ms, "
        f"search={result['timings_ms']['search']} ms)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
