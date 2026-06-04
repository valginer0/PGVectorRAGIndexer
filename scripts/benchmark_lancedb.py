import time
import statistics
import logging
import sys
import os

# Add parent directory to path so we can import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_config
from retriever_v2 import DocumentRetriever
from services import get_lancedb_adapter

# Configure logging
logging.basicConfig(level=logging.WARNING)

def run_benchmark():
    # Force-enable LanceDB retrieval
    config = get_config()
    config.retrieval.lancedb_enabled = True

    print("=== LanceDB 129k Latency Benchmark ===")
    print("Database path:", config.retrieval.lancedb_storage_path)
    
    # Initialize adapter and retriever
    adapter = get_lancedb_adapter()
    stats = adapter.get_statistics()
    print(f"Table stats: {stats['total_documents']} documents, {stats['total_chunks']} chunks")
    
    retriever = DocumentRetriever()
    
    queries = [
        "EV6",
        "charging",
        "battery",
        "system",
        "voltage",
        "EV6 charging issues",
        "12V battery test",
        "diagnostic report",
        "service bulletin",
        "compatibility failure",
        "power supply",
        "electrical engineering",
        "banana recipe",
        "nonexistentkeywordxyz",
        "charging port",
        "nominal reading",
        "vehicle diagnostic",
        "warranty coverage",
        "safety standards",
        "thermal runaway"
    ]
    
    # Warmup
    print("\nWarming up retriever...")
    for _ in range(3):
        retriever.search_hybrid("warmup query", top_k=10)
    
    print("\nRunning benchmark queries...")
    latencies = []
    
    for i, q in enumerate(queries, 1):
        start_time = time.perf_counter()
        results = retriever.search_hybrid(q, top_k=10)
        end_time = time.perf_counter()
        
        latency_ms = (end_time - start_time) * 1000
        latencies.append(latency_ms)
        print(f"[{i:02d}/{len(queries)}] Query: '{q}' -> {len(results)} results, Latency: {latency_ms:.2f}ms")
        
    print("\n=== Latency Summary ===")
    print(f"Total Queries: {len(queries)}")
    print(f"Min Latency:   {min(latencies):.2f}ms")
    print(f"Max Latency:   {max(latencies):.2f}ms")
    print(f"Average:       {statistics.mean(latencies):.2f}ms")
    print(f"Median:        {statistics.median(latencies):.2f}ms")
    
    # 95th percentile
    latencies.sort()
    p95_idx = int(len(latencies) * 0.95)
    print(f"p95 Latency:   {latencies[p95_idx]:.2f}ms")

if __name__ == "__main__":
    run_benchmark()
