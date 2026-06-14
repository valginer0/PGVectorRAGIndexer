#!/usr/bin/env python3
"""
PyInstaller packaging gate test for LanceDB (Phase 2 Spike 2 validation check 1).

Creates a tiny LanceDB table, builds a Tantivy FTS index, and runs a mock FTS
and vector search. Bundle with PyInstaller to verify that LanceDB's PyO3 Rust
extension loads correctly inside a frozen binary:

  venv/bin/pyinstaller --onefile scripts/lancedb_pyinstaller_test.py
  dist/lancedb_pyinstaller_test

PASS: All operations succeed and the exit code is 0.
FAIL: The binary throws:
        ModuleNotFoundError: No module named 'lance.vector'
      or any other ImportError, meaning PyInstaller cannot resolve the dynamic
      library tree of LanceDB's Rust/PyO3 extension on this system.

This test is a mandatory acceptance gate for the LanceDB desktop-deployment path.
If it fails, the deployment model must fall back to the server-centric path
(PG17 + pg_textsearch) or require additional spec-file hooks for PyInstaller.
"""

import sys
import tempfile


def _import_check() -> bool:
    """Verify that the critical lancedb modules load without error."""
    try:
        import lancedb  # noqa: F401
        import pyarrow  # noqa: F401
        return True
    except ImportError as exc:
        print(f"FAIL: import error: {exc}", file=sys.stderr)
        return False


def main() -> int:
    if not _import_check():
        return 1

    import lancedb
    import pyarrow as pa

    print(f"lancedb version : {lancedb.__version__}")
    try:
        import lance
        print(f"lance version   : {lance.__version__}")
    except Exception:
        pass

    with tempfile.TemporaryDirectory() as tmpdir:
        db = lancedb.connect(tmpdir)

        # Minimal schema: text field for FTS, 3-dim vector for vector search.
        data = pa.table({
            "id": pa.array([1, 2, 3], type=pa.int32()),
            "text": pa.array(
                ["EV6 charging issue", "battery voltage nominal", "EV7 model spec"],
                type=pa.utf8(),
            ),
            "vec": pa.array(
                [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6], [0.7, 0.8, 0.9]],
                type=pa.list_(pa.float32(), 3),
            ),
        })
        tbl = db.create_table("test", data=data, mode="overwrite")
        print("Table creation  : OK")

        try:
            tbl.create_fts_index("text", replace=True)
        except TypeError:
            tbl.create_fts_index("text")
        print("FTS index       : OK")

        fts_result = tbl.search("EV6 charging", query_type="fts").limit(3).to_arrow()
        n_fts = len(fts_result)
        print(f"FTS search      : OK ({n_fts} result(s))")

        vec_result = (
            tbl.search([0.1, 0.2, 0.3], vector_column_name="vec")
            .limit(2)
            .to_arrow()
        )
        n_vec = len(vec_result)
        print(f"Vector search   : OK ({n_vec} result(s))")

    print("PASS: All LanceDB operations succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
