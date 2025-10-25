"""Shared UI helpers for the desktop application."""

from typing import Optional

from PySide6.QtWidgets import QComboBox


def populate_document_type_combo(
    combo: QComboBox,
    api_client,
    logger,
    *,
    blank_option: str = "",
    log_context: str = "document type loader"
) -> Optional[int]:
    """Populate a QComboBox with document types from the API.

    Args:
        combo: Combo box to populate.
        api_client: API client exposing ``get_metadata_values``.
        logger: Logger for success/error messages.
        blank_option: Label to insert as the first "all types" option.
        log_context: Additional context for log messages.

    Returns:
        The number of document types loaded on success, otherwise ``None``.
    """
    try:
        types = api_client.get_metadata_values("type")
    except Exception as exc:  # pragma: no cover - defensive logging path
        logger.error(f"Failed to load document types for {log_context}: {exc}")
        return None

    current_text = combo.currentText()

    combo.blockSignals(True)
    combo.clear()
    combo.addItem(blank_option)

    for doc_type in sorted(types):
        if doc_type:
            combo.addItem(doc_type)

    if current_text:
        index = combo.findText(current_text)
        if index >= 0:
            combo.setCurrentIndex(index)
        else:
            combo.setCurrentText(current_text)

    combo.blockSignals(False)

    logger.info(f"Loaded {len(types)} document types for {log_context}")
    return len(types)
