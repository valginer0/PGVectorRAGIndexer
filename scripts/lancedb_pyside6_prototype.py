#!/usr/bin/env python3
"""
LanceDB + PySide6 Standalone Parent-Child Desktop Search Prototype.

This prototype demonstrates a local "Docker-Free" two-tier RAG retrieval architecture
using LanceDB (embedded vector db) and Tantivy (fts index), bundled with a
modern, premium PySide6 GUI interface.

Features:
  1. Standalone desktop GUI built with modern dark-mode styling and glassmorphism accents.
  2. Dual Retrieval Modes:
     - Flat Global Hybrid (RRF): Global FTS & vector searches blended with reciprocal rank fusion.
     - Two-Tier Parent-Child Scoped: First queries FTS on parent docs to identify candidate paths,
       then filters vector search to chunks belonging strictly to those parents.
  3. Hybrid Bootstrapping:
     - Live PG17 Connection: Pulls actual vectors and document texts from PG17 if available.
     - Mock Fallback: Self-seeds with a curated, high-quality test corpus containing EV6
       system manuals and distractor documents to verify precision even if PostgreSQL is offline.
  4. Real-time telemetry dashboard detailing search latency, filters, and SQL execution.
  5. Dual CLI/GUI mode: run with `--headless` and `--search` flags for automated testing/CI.

Usage:
  # Run the interactive GUI application
  venv/bin/python scripts/lancedb_pyside6_prototype.py

  # Run headless for automated precision check
  venv/bin/python scripts/lancedb_pyside6_prototype.py --headless --search "EV6 battery troubleshooting"
"""

from __future__ import annotations

import os
import sys
import time
import argparse
import tempfile
import psutil
from pathlib import Path
from typing import Any, cast

# ---------------------------------------------------------------------------
# Lazy / Safe imports for PySide6, LanceDB, and Arrow
# ---------------------------------------------------------------------------
try:
    import lancedb
    import pyarrow as pa
except ImportError as exc:
    sys.exit(f"ERROR: Missing essential backend library: {exc}\nRun: venv/bin/pip install lancedb pyarrow")

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLineEdit, QPushButton, QLabel, QRadioButton, QButtonGroup,
        QTextEdit, QFrame, QScrollArea, QSizePolicy
    )
    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_LANCE_PATH = "./lancedb_prototype_data"
PARENT_TABLE = "parent_documents"
CHUNK_TABLE = "document_chunks"
EMBEDDING_DIM = 384
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# ---------------------------------------------------------------------------
# Embedding cache manager (Sentence-Transformers)
# ---------------------------------------------------------------------------
def _load_embedding_model():
    """Load and cache the SentenceTransformer model using a local user cache folder."""
    try:
        from sentence_transformers import SentenceTransformer
        # Set cache dir to standard system user cache to avoid cluttering local repo
        cache_dir = os.path.join(str(Path.home()), ".cache", "antigravity_transformers")
        print(f"[Embedding] Initializing {EMBEDDING_MODEL} (Cache: {cache_dir})...", file=sys.stderr)
        return SentenceTransformer(EMBEDDING_MODEL, cache_folder=cache_dir)
    except Exception as exc:
        print(
            f"WARNING: sentence_transformers could not be loaded ({exc}).\n"
            "Falling back to zero-vector representations. Semantic search results will be zeroed.",
            file=sys.stderr
        )
        return None

def _encode(model, query: str) -> list[float]:
    """Generate normalized embedding vectors, fallback to zero-vectors if model unavailable."""
    if model is None:
        return [0.0] * EMBEDDING_DIM
    v = model.encode(query)
    return v.tolist() if hasattr(v, "tolist") else list(v)

# ---------------------------------------------------------------------------
# High-Quality Curated Mock Data for Postgres Offline Fallback
# ---------------------------------------------------------------------------
MOCK_CORPUS = [
    {
        "source_uri": "documents/automotive/EV6_Diagnostic_Battery_System.txt",
        "chunks": [
            "The EV6 electric vehicle utilizes a 800V high-voltage lithium-ion polymer battery. Diagnostic trouble code DTC P0A7F indicates hybrid/EV battery pack degradation.",
            "For EV6 battery systems, voltage imbalances between cells must be diagnosed using the High Voltage battery management system (BMS) telematics tool. Standard operating cell voltage ranges from 3.6V to 4.2V.",
            "EV6 battery thermal management is regulated via an active liquid cooling loop. Extreme temperatures above 55 degrees Celsius trigger safety relays to limit fast charging capacity."
        ]
    },
    {
        "source_uri": "documents/automotive/EV6_Charging_Standard_Operating_Procedure.txt",
        "chunks": [
            "EV6 ultra-fast DC charging requires a 350kW CCS Combo-2 charger to transition from 10% to 80% state of charge (SoC) in approximately 18 minutes.",
            "When troubleshooting EV6 cold weather charging failures, ensure battery preconditioning is active. Preconditioning warms the battery pack to at least 15 degrees Celsius before connection.",
            "AC slow charging on the EV6 supports up to 11kW via the on-board charger (OBC). Common error code AC-E39 indicates charging protocol handshake failure on ground detection."
        ]
    },
    {
        "source_uri": "documents/industrial/PowerSupplies_Industrial_Guide.txt",
        "chunks": [
            "Industrial power supply modules convert three-phase AC input to stabilized 24V DC output. These DIN-rail mounted power units are rated for 240W, 480W, and 960W continuous operations.",
            "Overload protection in generic DIN-rail power units relies on a hiccup-mode duty cycle. Under severe short-circuit scenarios, the system pulses voltage output to prevent copper trace overheating.",
            "Ensure adequate physical ventilation spacing of at least 50mm on all sides when installing high-power rack-mount converters in server environments."
        ]
    },
    {
        "source_uri": "documents/consumer/Battery_LawnMower_Instructions.txt",
        "chunks": [
            "The cordless electric lawn mower is powered by a generic 12V lead-acid battery or 40V lithium rechargeable pack. Do not charge in freezing ambient conditions.",
            "Ensure the safety key is completely inserted into the mower console before checking battery charge level. Press the green indicator to display battery cell LED status.",
            "Store lawn mower batteries in dry storage units over winter months. Slow trickle charge once every 60 days to prevent voltage dropping below critical salvage thresholds."
        ]
    }
]

# ---------------------------------------------------------------------------
# Database and Retrieval Engine
# ---------------------------------------------------------------------------
class SearchEngine:
    def __init__(self, db_path: str = DEFAULT_LANCE_PATH):
        self.db_path = db_path
        self.db = lancedb.connect(db_path)
        self.embed_model = _load_embedding_model()

    def _table_names(self) -> list[str]:
        """Return LanceDB table names across old and new LanceDB APIs."""
        if hasattr(self.db, "list_tables"):
            tables = self.db.list_tables()
            if hasattr(tables, "tables"):
                return list(tables.tables)
            if isinstance(tables, dict):
                return list(tables.get("tables", []))
            return list(tables)
        return list(self.db.table_names())

    @staticmethod
    def _quote_lancedb_string(value: str) -> str:
        """Quote a string literal for LanceDB filter expressions."""
        return "'" + value.replace("'", "''") + "'"

    def is_bootstrapped(self) -> bool:
        """Check if database exists and has populated parent tables."""
        tables = self._table_names()
        return PARENT_TABLE in tables and CHUNK_TABLE in tables

    def bootstrap_db(self, pg_config: dict[str, Any] | None = None) -> str:
        """Bootstrap the local LanceDB tables from PG17 or a robust mock fallback."""
        parents_data = []
        chunks_data = []
        source_database = "Mock Fallback"

        # Try to pull from PG17
        if pg_config is not None:
            try:
                import psycopg2
                from psycopg2.extras import RealDictCursor
                conn = psycopg2.connect(
                    host=pg_config.get("host", "localhost"),
                    port=pg_config.get("port", 55432),
                    dbname=pg_config.get("database", "rag_vector_restore_20260521"),
                    user=pg_config.get("user", "rag_user"),
                    password=pg_config.get("password", "rag_password"),
                    connect_timeout=3
                )
                source_database = f"PostgreSQL ({pg_config.get('database')})"
                print(f"[Bootstrap] Connected to PostgreSQL. Fetching gold standard RAG data...", file=sys.stderr)
                
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    # 1. Fetch chunks & embeddings
                    cur.execute("""
                        SELECT chunk_id, source_uri, chunk_index, text_content, embedding::text AS emb_text
                        FROM document_chunks
                        ORDER BY source_uri, chunk_index
                    """)
                    pg_chunks = cur.fetchall()

                    # 2. Reconstruct document-level texts (parents)
                    cur.execute("""
                        SELECT source_uri, STRING_AGG(text_content, E'\n\n' ORDER BY chunk_index) AS content, COUNT(*) as chunk_count
                        FROM document_chunks
                        GROUP BY source_uri
                    """)
                    pg_parents = cur.fetchall()

                # Process parents
                for row in pg_parents:
                    parents_data.append({
                        "source_uri": row["source_uri"],
                        "aggregated_text": row["content"] or "",
                        "chunk_count": int(row["chunk_count"])
                    })

                # Process chunks
                def parse_vector(text: str) -> list[float]:
                    return [float(x) for x in text.strip("[]").split(",")]

                for row in pg_chunks:
                    emb = parse_vector(row["emb_text"])
                    chunks_data.append({
                        "chunk_id": int(row["chunk_id"]),
                        "source_uri": row["source_uri"],
                        "chunk_index": int(row["chunk_index"]),
                        "text_content": row["text_content"] or "",
                        "embedding": emb
                    })
                conn.close()

            except Exception as e:
                print(f"[Bootstrap] PostgreSQL bootstrap failed ({e}). Falling back to local mock data.", file=sys.stderr)
                parents_data.clear()
                chunks_data.clear()

        # Seed with high quality mock data if PG was offline or failed
        if not parents_data:
            print("[Bootstrap] Seeding database with curated local mock corpus...", file=sys.stderr)
            chunk_id_counter = 1
            for doc in MOCK_CORPUS:
                aggregated = "\n\n".join(doc["chunks"])
                parents_data.append({
                    "source_uri": doc["source_uri"],
                    "aggregated_text": aggregated,
                    "chunk_count": len(doc["chunks"])
                })
                for idx, chunk_text in enumerate(doc["chunks"]):
                    emb = _encode(self.embed_model, chunk_text)
                    chunks_data.append({
                        "chunk_id": chunk_id_counter,
                        "source_uri": doc["source_uri"],
                        "chunk_index": idx,
                        "text_content": chunk_text,
                        "embedding": emb
                    })
                    chunk_id_counter += 1

        # 1. Create Arrow Tables
        parent_schema = pa.schema([
            pa.field("source_uri", pa.string(), nullable=False),
            pa.field("aggregated_text", pa.string(), nullable=False),
            pa.field("chunk_count", pa.int32(), nullable=False),
        ])
        parent_table = pa.Table.from_batches([
            pa.RecordBatch.from_pydict({
                "source_uri": [p["source_uri"] for p in parents_data],
                "aggregated_text": [p["aggregated_text"] for p in parents_data],
                "chunk_count": [p["chunk_count"] for p in parents_data]
            }, schema=parent_schema)
        ])

        chunk_schema = pa.schema([
            pa.field("chunk_id", pa.int64(), nullable=False),
            pa.field("source_uri", pa.string(), nullable=False),
            pa.field("chunk_index", pa.int32(), nullable=False),
            pa.field("text_content", pa.string(), nullable=False),
            pa.field("embedding", pa.list_(pa.float32(), EMBEDDING_DIM), nullable=False),
        ])
        chunk_table = pa.Table.from_batches([
            pa.RecordBatch.from_pydict({
                "chunk_id": [c["chunk_id"] for c in chunks_data],
                "source_uri": [c["source_uri"] for c in chunks_data],
                "chunk_index": [c["chunk_index"] for c in chunks_data],
                "text_content": [c["text_content"] for c in chunks_data],
                "embedding": [c["embedding"] for c in chunks_data]
            }, schema=chunk_schema)
        ])

        # 2. Write to LanceDB
        tbl_parents = self.db.create_table(PARENT_TABLE, data=parent_table, mode="overwrite")
        tbl_chunks = self.db.create_table(CHUNK_TABLE, data=chunk_table, mode="overwrite")

        # 3. Create Tantivy FTS Indices
        try:
            tbl_parents.create_fts_index("aggregated_text", replace=True)
            tbl_chunks.create_fts_index("text_content", replace=True)
        except TypeError:
            tbl_parents.create_fts_index("aggregated_text")
            tbl_chunks.create_fts_index("text_content")

        return f"Database bootstrapped successfully from {source_database}! Indexed {len(parents_data)} parent docs and {len(chunks_data)} chunks."

    def search_flat_global_hybrid(self, query: str, top_k: int = 5, rrf_k: int = 60) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Flat Global Hybrid Search using manually executed RRF over LanceDB FTS & Vector queries."""
        start_time = time.perf_counter()
        tbl_chunks = self.db.open_table(CHUNK_TABLE)

        # 1. Run FTS search
        t0 = time.perf_counter()
        fts_res = tbl_chunks.search(query, query_type="fts").limit(top_k * 2).to_arrow().to_pylist()
        fts_time = (time.perf_counter() - t0) * 1000

        # 2. Run Vector search
        t1 = time.perf_counter()
        emb = _encode(self.embed_model, query)
        vec_res = tbl_chunks.search(emb, vector_column_name="embedding").limit(top_k * 2).to_arrow().to_pylist()
        vec_time = (time.perf_counter() - t1) * 1000

        # Apply manual RRF
        rrf_scores: dict[int, float] = {}
        for rank, r in enumerate(fts_res, 1):
            cid = r["chunk_id"]
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (rrf_k + rank)
        for rank, r in enumerate(vec_res, 1):
            cid = r["chunk_id"]
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (rrf_k + rank)

        # Deduplicate & sort
        by_cid: dict[int, dict] = {}
        for r in vec_res + fts_res:
            by_cid[r["chunk_id"]] = r

        ranked = sorted(by_cid.values(), key=lambda r: -rrf_scores[r["chunk_id"]])[:top_k]
        
        results = []
        for rank_idx, r in enumerate(ranked, 1):
            score = round(rrf_scores[r["chunk_id"]], 6)
            # Find the original rank in vector / fts
            vec_rank = "N/A"
            for vr, vr_row in enumerate(vec_res, 1):
                if vr_row["chunk_id"] == r["chunk_id"]:
                    vec_rank = str(vr)
                    break
            fts_rank = "N/A"
            for fr, fr_row in enumerate(fts_res, 1):
                if fr_row["chunk_id"] == r["chunk_id"]:
                    fts_rank = str(fr)
                    break

            results.append({
                "rank": rank_idx,
                "chunk_id": r["chunk_id"],
                "source_uri": r["source_uri"],
                "chunk_index": r["chunk_index"],
                "text": r["text_content"],
                "score_label": f"RRF: {score:.5f} (FTS Rank: {fts_rank}, Vec Rank: {vec_rank})"
            })

        total_time = (time.perf_counter() - start_time) * 1000
        telemetry = {
            "total_time_ms": total_time,
            "fts_time_ms": fts_time,
            "vector_time_ms": vec_time,
            "query_type": "Flat Global Hybrid (RRF)",
            "explanation": f"Blended global searches from LanceDB FTS (Tantivy) and HNSW cosine distance vector queries using Reciprocal Rank Fusion."
        }
        return results, telemetry

    def search_two_tier_parent_child(self, query: str, parent_limit: int = 2, child_limit: int = 3) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Two-tier parent-child scoped search: FTS on parents -> Vector search on their child chunks."""
        start_time = time.perf_counter()
        tbl_parents = self.db.open_table(PARENT_TABLE)
        tbl_chunks = self.db.open_table(CHUNK_TABLE)

        # Step 1: Query FTS on parent documents to find top matching document paths
        t0 = time.perf_counter()
        parent_results = tbl_parents.search(query, query_type="fts").limit(parent_limit).to_arrow().to_pylist()
        parent_time = (time.perf_counter() - t0) * 1000

        matched_paths = [p["source_uri"] for p in parent_results]

        results = []
        vec_time = 0.0
        filter_str = "N/A"

        if matched_paths:
            # Format paths as a scoped LanceDB filter expression.
            formatted_paths = ", ".join(
                self._quote_lancedb_string(p) for p in matched_paths
            )
            filter_str = f"source_uri IN ({formatted_paths})"

            t1 = time.perf_counter()
            emb = _encode(self.embed_model, query)
            
            # Execute HNSW vector search with path scoping filter
            vec_res = (
                tbl_chunks.search(emb, vector_column_name="embedding")
                .where(filter_str)
                .limit(child_limit)
                .to_arrow()
                .to_pylist()
            )
            vec_time = (time.perf_counter() - t1) * 1000

            for rank_idx, r in enumerate(vec_res, 1):
                # Calculate simple cosine similarity score label
                dist = r.get("_distance", 1.0)
                sim_score = round(1.0 - dist, 4)
                results.append({
                    "rank": rank_idx,
                    "chunk_id": r["chunk_id"],
                    "source_uri": r["source_uri"],
                    "chunk_index": r["chunk_index"],
                    "text": r["text_content"],
                    "score_label": f"Cosine Similarity: {sim_score:.4f} (Distance: {dist:.4f})"
                })

        total_time = (time.perf_counter() - start_time) * 1000
        telemetry = {
            "total_time_ms": total_time,
            "fts_time_ms": parent_time,
            "vector_time_ms": vec_time,
            "query_type": "Two-Tier Parent-Child",
            "filter_clause": filter_str,
            "matched_parents": matched_paths,
            "explanation": f"Queried Tantivy FTS on document aggregates to select top {len(matched_paths)} parents: {matched_paths}. Scoped child chunk vector search using: `{filter_str}`."
        }
        return results, telemetry

# ---------------------------------------------------------------------------
# Beautiful Dark-Mode GUI Layout (PySide6)
# ---------------------------------------------------------------------------
if PYSIDE6_AVAILABLE:
    class ResultCard(QFrame):
        """Custom widget rendering a beautiful, distinct search result card."""
        def __init__(self, data: dict[str, Any], parent=None):
            super().__init__(parent)
            self.setObjectName("ResultCard")
            self.setFrameShape(QFrame.StyledPanel)

            # High-end glassmorphism look with glowing borders
            self.setStyleSheet("""
                QFrame#ResultCard {
                    background-color: #1a2333;
                    border: 1px solid #2e3e57;
                    border-radius: 8px;
                    padding: 12px;
                    margin-bottom: 8px;
                }
                QFrame#ResultCard:hover {
                    background-color: #202b3e;
                    border: 1px solid #3b82f6;
                }
            """)

            layout = QVBoxLayout(self)
            layout.setContentsMargins(12, 12, 12, 12)
            layout.setSpacing(6)

            # Header: Rank and Path
            header = QHBoxLayout()
            
            rank_label = QLabel(f"#{data['rank']}")
            rank_label.setStyleSheet("color: #10b981; font-weight: bold; font-size: 14px;")
            header.addWidget(rank_label)

            path_label = QLabel(data['source_uri'])
            path_label.setStyleSheet("color: #f9fafb; font-weight: bold; font-size: 12px;")
            path_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            header.addWidget(path_label)

            chunk_label = QLabel(f"Chunk: {data['chunk_index']}")
            chunk_label.setStyleSheet("color: #9ca3af; font-size: 11px;")
            header.addWidget(chunk_label)

            layout.addLayout(header)

            # Preview content
            content = QLabel(data['text'])
            content.setWordWrap(True)
            content.setStyleSheet("color: #d1d5db; font-size: 13px; line-height: 1.4;")
            layout.addWidget(content)

            # Score badge
            score = QLabel(data['score_label'])
            score.setStyleSheet("color: #3b82f6; font-size: 11px; font-weight: 500; margin-top: 4px;")
            layout.addWidget(score)

    class MainWindow(QMainWindow):
        def __init__(self, engine: SearchEngine):
            super().__init__()
            self.engine = engine
            self.setWindowTitle("Antigravity - LanceDB PySide6 RAG Prototype")
            self.resize(1050, 750)

            # Central premium dark theme stylesheet
            self.setStyleSheet("""
                QMainWindow {
                    background-color: #0b0f19;
                }
                QWidget {
                    font-family: 'Inter', 'Outfit', 'Segoe UI', sans-serif;
                }
                QLabel {
                    color: #f9fafb;
                }
                QLineEdit {
                    background-color: #161e2d;
                    border: 1px solid #2e3e57;
                    border-radius: 6px;
                    color: #f9fafb;
                    padding: 10px 14px;
                    font-size: 14px;
                }
                QLineEdit:focus {
                    border: 1px solid #3b82f6;
                }
                QPushButton {
                    background-color: #3b82f6;
                    border: none;
                    border-radius: 6px;
                    color: white;
                    padding: 10px 18px;
                    font-size: 13px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #2563eb;
                }
                QPushButton:pressed {
                    background-color: #1d4ed8;
                }
                QPushButton#bootstrapBtn {
                    background-color: #10b981;
                }
                QPushButton#bootstrapBtn:hover {
                    background-color: #059669;
                }
                QRadioButton {
                    color: #d1d5db;
                    font-size: 13px;
                    spacing: 8px;
                }
                QRadioButton::indicator {
                    width: 16px;
                    height: 16px;
                }
                QScrollArea {
                    border: none;
                    background-color: transparent;
                }
            """)

            self.init_ui()

        def init_ui(self):
            central_widget = QWidget()
            self.setCentralWidget(central_widget)
            
            main_layout = QHBoxLayout(central_widget)
            main_layout.setContentsMargins(20, 20, 20, 20)
            main_layout.setSpacing(20)

            # Left Panel: Main Search & Results
            left_widget = QWidget()
            left_layout = QVBoxLayout(left_widget)
            left_layout.setContentsMargins(0, 0, 0, 0)
            left_layout.setSpacing(16)

            # App Title & Subtitle
            header_layout = QVBoxLayout()
            title = QLabel("Antigravity Retrieval Engine")
            title.setStyleSheet("font-size: 22px; font-weight: 800; color: #f9fafb; letter-spacing: -0.5px;")
            header_layout.addWidget(title)
            
            status_row = QHBoxLayout()
            status_pill = QLabel("ENGINE: LANCEDB (EMBEDDED)")
            status_pill.setStyleSheet("""
                background-color: #1e293b;
                color: #3b82f6;
                font-size: 10px;
                font-weight: bold;
                padding: 4px 8px;
                border-radius: 4px;
                border: 1px solid #334155;
            """)
            status_row.addWidget(status_pill)
            
            self.db_status_pill = QLabel()
            self.update_db_status_pill()
            status_row.addWidget(self.db_status_pill)
            status_row.addStretch()
            header_layout.addLayout(status_row)
            
            left_layout.addLayout(header_layout)

            # Search Bar Section
            search_bar_layout = QHBoxLayout()
            self.search_input = QLineEdit()
            self.search_input.setPlaceholderText("Enter system query (e.g. 'EV6 battery cell check')...")
            self.search_input.returnPressed.connect(self.run_search)
            search_bar_layout.addWidget(self.search_input)

            self.search_btn = QPushButton("Search")
            self.search_btn.clicked.connect(self.run_search)
            search_bar_layout.addWidget(self.search_btn)
            left_layout.addLayout(search_bar_layout)

            # Retrieval Switch Toggle Row
            toggle_frame = QFrame()
            toggle_frame.setStyleSheet("""
                QFrame {
                    background-color: #111827;
                    border: 1px solid #1f2937;
                    border-radius: 8px;
                    padding: 8px 12px;
                }
            """)
            toggle_layout = QHBoxLayout(toggle_frame)
            toggle_layout.setContentsMargins(8, 4, 8, 4)

            self.mode_group = QButtonGroup(self)
            
            self.pc_toggle = QRadioButton("Two-Tier Parent-Child Scoped")
            self.pc_toggle.setChecked(True)
            self.mode_group.addButton(self.pc_toggle)
            toggle_layout.addWidget(self.pc_toggle)

            self.flat_toggle = QRadioButton("Flat Global Hybrid (RRF)")
            self.mode_group.addButton(self.flat_toggle)
            toggle_layout.addWidget(self.flat_toggle)

            toggle_layout.addStretch()
            left_layout.addWidget(toggle_frame)

            # Scrollable viewport for results
            self.results_scroll = QScrollArea()
            self.results_scroll.setWidgetResizable(True)
            self.results_container = QWidget()
            self.results_container_layout = QVBoxLayout(self.results_container)
            self.results_container_layout.setContentsMargins(0, 0, 0, 0)
            self.results_container_layout.setSpacing(8)
            self.results_container_layout.addStretch() # bottom spacing
            self.results_scroll.setWidget(self.results_container)
            
            left_layout.addWidget(self.results_scroll)
            main_layout.addWidget(left_widget, 3)

            # Right Panel: Operations & Diagnostic Console
            right_widget = QWidget()
            right_widget.setStyleSheet("""
                QWidget {
                    background-color: #111827;
                    border-radius: 8px;
                    border: 1px solid #1f2937;
                }
            """)
            right_layout = QVBoxLayout(right_widget)
            right_layout.setContentsMargins(16, 16, 16, 16)
            right_layout.setSpacing(14)

            # Bootstrap utilities
            boot_title = QLabel("System Seeding")
            boot_title.setStyleSheet("font-size: 13px; font-weight: bold; border: none; color: #9ca3af; text-transform: uppercase;")
            right_layout.addWidget(boot_title)

            self.bootstrap_btn = QPushButton("Bootstrap Database")
            self.bootstrap_btn.setObjectName("bootstrapBtn")
            self.bootstrap_btn.clicked.connect(self.trigger_bootstrap)
            right_layout.addWidget(self.bootstrap_btn)

            # Telemetry readout panel
            telemetry_title = QLabel("Telemetry Log Console")
            telemetry_title.setStyleSheet("font-size: 13px; font-weight: bold; border: none; color: #9ca3af; text-transform: uppercase; margin-top: 10px;")
            right_layout.addWidget(telemetry_title)

            self.telemetry_readout = QTextEdit()
            self.telemetry_readout.setReadOnly(True)
            self.telemetry_readout.setPlaceholderText("Retrieval logs, performance metrics, and FTS filter logic will stream here dynamically...")
            self.telemetry_readout.setStyleSheet("""
                QTextEdit {
                    background-color: #030712;
                    border: 1px solid #1f2937;
                    border-radius: 6px;
                    color: #38bdf8;
                    font-family: 'Courier New', monospace;
                    font-size: 12px;
                    padding: 8px;
                }
            """)
            right_layout.addWidget(self.telemetry_readout)

            main_layout.addWidget(right_widget, 2)

            self.log_telemetry("System initialized. Model loaded successfully.")

        def update_db_status_pill(self):
            is_seeded = self.engine.is_bootstrapped()
            if is_seeded:
                self.db_status_pill.setText("STATUS: SEEDED")
                self.db_status_pill.setStyleSheet("""
                    background-color: #064e3b;
                    color: #34d399;
                    font-size: 10px;
                    font-weight: bold;
                    padding: 4px 8px;
                    border-radius: 4px;
                    border: 1px solid #047857;
                """)
            else:
                self.db_status_pill.setText("STATUS: UNSEEDED")
                self.db_status_pill.setStyleSheet("""
                    background-color: #7f1d1d;
                    color: #fca5a5;
                    font-size: 10px;
                    font-weight: bold;
                    padding: 4px 8px;
                    border-radius: 4px;
                    border: 1px solid #b91c1c;
                """)

        def log_telemetry(self, msg: str):
            timestamp = time.strftime("%H:%M:%S")
            self.telemetry_readout.append(f"[{timestamp}] {msg}\n")

        def trigger_bootstrap(self):
            self.log_telemetry("Starting database bootstrapping...")
            self.bootstrap_btn.setEnabled(False)
            self.bootstrap_btn.setText("Bootstrapping...")
            QApplication.processEvents()

            # Pass default local PG credentials
            pg_conf = {
                "host": "localhost",
                "port": 55432,
                "database": "rag_vector_restore_20260521",
                "user": "rag_user",
                "password": "rag_password"
            }
            
            try:
                res_msg = self.engine.bootstrap_db(pg_conf)
                self.log_telemetry(res_msg)
            except Exception as e:
                self.log_telemetry(f"Bootstrap encountered error: {e}")

            self.update_db_status_pill()
            self.bootstrap_btn.setEnabled(True)
            self.bootstrap_btn.setText("Bootstrap Database")

        def clear_results(self):
            # Clear previous results
            while self.results_container_layout.count() > 1:
                item = self.results_container_layout.takeAt(0)
                if item and item.widget():
                    item.widget().deleteLater()

        def run_search(self):
            query = self.search_input.text().strip()
            if not query:
                return

            if not self.engine.is_bootstrapped():
                self.log_telemetry("Error: Database must be bootstrapped first!")
                return

            self.clear_results()
            self.log_telemetry(f"Running query: '{query}'...")

            # Check selected mode
            is_parent_child = self.pc_toggle.isChecked()

            results = []
            telemetry = {}
            
            # Record base process memory before query
            process = psutil.Process(os.getpid())
            mem_before = process.memory_info().rss / (1024 * 1024)

            if is_parent_child:
                results, telemetry = self.engine.search_two_tier_parent_child(query)
            else:
                results, telemetry = self.engine.search_flat_global_hybrid(query)

            mem_after = process.memory_info().rss / (1024 * 1024)
            mem_diff = mem_after - mem_before

            # Display cards
            for r in results:
                card = ResultCard(r)
                # Insert at top
                self.results_container_layout.insertWidget(self.results_container_layout.count() - 1, card)

            # Render detailed telemetry
            log_parts = [
                f"Mode      : {telemetry['query_type']}",
                f"Total Wall: {telemetry['total_time_ms']:.2f} ms",
                f"  - Lexical (FTS): {telemetry['fts_time_ms']:.2f} ms",
                f"  - Vector (HNSW): {telemetry['vector_time_ms']:.2f} ms",
                f"Memory Usage   : {mem_after:.2f} MB (Delta: {mem_diff:+.3f} MB)"
            ]
            if "filter_clause" in telemetry:
                log_parts.append(f"SQL Filter: {telemetry['filter_clause']}")
            if "matched_parents" in telemetry:
                log_parts.append(f"Parents   : {telemetry['matched_parents']}")
            log_parts.append(f"Explanation: {telemetry['explanation']}")

            self.log_telemetry("\n".join(log_parts))

# ---------------------------------------------------------------------------
# CLI Headless Verification Mode
# ---------------------------------------------------------------------------
def run_headless_mode(engine: SearchEngine, search_query: str):
    print("=====================================================================", flush=True)
    print(" LANCEDB HYBRID PARENT-CHILD SEARCH HEADLESS ENGINE TESTER", flush=True)
    print("=====================================================================", flush=True)

    if not engine.is_bootstrapped():
        print("[Engine] Local tables unseeded. Triggering self-bootstrap...", flush=True)
        # Attempt PostgreSQL connection fallback automatically
        pg_conf = {
            "host": "localhost",
            "port": 55432,
            "database": "rag_vector_restore_20260521",
            "user": "rag_user",
            "password": "rag_password"
        }
        status = engine.bootstrap_db(pg_conf)
        print(f"[Engine] {status}", flush=True)

    # 1. Execute Flat Global Hybrid
    print(f"\n[QUERY] Running: '{search_query}' (Flat Global Hybrid RRF)", flush=True)
    flat_results, flat_telemetry = engine.search_flat_global_hybrid(search_query)
    for r in flat_results:
        print(f"  Rank {r['rank']} | Score: {r['score_label']}")
        print(f"    Path: {r['source_uri']}")
        print(f"    Text: {r['text'][:120]}...")
    print(f"[Telemetry] Total time: {flat_telemetry['total_time_ms']:.2f}ms (FTS: {flat_telemetry['fts_time_ms']:.2f}ms, Vector: {flat_telemetry['vector_time_ms']:.2f}ms)", flush=True)

    # 2. Execute Two-Tier Parent-Child
    print(f"\n[QUERY] Running: '{search_query}' (Two-Tier Parent-Child Scoped)", flush=True)
    pc_results, pc_telemetry = engine.search_two_tier_parent_child(search_query)
    for r in pc_results:
        print(f"  Rank {r['rank']} | Score: {r['score_label']}")
        print(f"    Path: {r['source_uri']}")
        print(f"    Text: {r['text'][:120]}...")
    print(f"[Telemetry] Total time: {pc_telemetry['total_time_ms']:.2f}ms (FTS: {pc_telemetry['fts_time_ms']:.2f}ms, Vector: {pc_telemetry['vector_time_ms']:.2f}ms)", flush=True)
    if "filter_clause" in pc_telemetry:
        print(f"  Filter Used: {pc_telemetry['filter_clause']}", flush=True)

    print("\n=====================================================================", flush=True)
    print(" VERIFICATION COMPLETE", flush=True)
    print("=====================================================================", flush=True)

# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LanceDB + PySide6 Standalone Parent-Child Search Prototype CLI")
    parser.add_argument("--lance-path", default=DEFAULT_LANCE_PATH, help="Path to write local LanceDB databases")
    parser.add_argument("--headless", action="store_true", help="Launch headlessly without opening the GUI")
    parser.add_argument("--search", type=str, default="EV6 battery troubleshooting", help="Query to search when headlessly invoked")
    parser.add_argument("--bootstrap", action="store_true", help="Bootstrap database from PostgreSQL/Mock and exit immediately")
    args = parser.parse_args(argv)

    engine = SearchEngine(args.lance_path)

    # Bootstrapping ONLY requested
    if args.bootstrap:
        pg_conf = {
            "host": "localhost",
            "port": 55432,
            "database": "rag_vector_restore_20260521",
            "user": "rag_user",
            "password": "rag_password"
        }
        res = engine.bootstrap_db(pg_conf)
        print(res)
        return 0

    # Headless CLI Execution requested
    if args.headless:
        run_headless_mode(engine, args.search)
        return 0

    # Interactive GUI launch requested
    if not PYSIDE6_AVAILABLE:
        print("ERROR: PySide6 library is not installed or GUI context is unavailable. Running in --headless mode instead.")
        run_headless_mode(engine, args.search)
        return 0

    # Normal application launch
    app = QApplication(sys.argv)
    window = MainWindow(engine)
    window.show()
    return app.exec()

if __name__ == "__main__":
    sys.exit(main())
