"""
Shared utilities for file hashing.
Uses xxHash for high-performance non-cryptographic hashing.
"""

import xxhash
from pathlib import Path
import hashlib

def calculate_file_hash(path: Path, chunk_size: int = 8192) -> str:
    """
    Calculate xxHash64 of a file.
    
    Args:
        path: Path to the file.
        chunk_size: Size of chunks to read.
        
    Returns:
        Hexadecimal string of the hash.
    """
    hasher = xxhash.xxh64()
    with open(path, 'rb') as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()

def calculate_source_id(source_uri: str) -> str:
    """
    Calculate deterministic document ID from source URI.
    Matches the logic used in the backend for ID generation.
    
    Args:
        source_uri: Source URI of the document.
        
    Returns:
        SHA256 hash of the URI (first 16 chars usually, but we return full here 
        and let caller truncate if needed, or matched backend implementation).
    """
    # Note: Backend uses first 16 chars of sha256 of the URI.
    # We match this exactly to ensure client generates the same ID as server.
    return hashlib.sha256(source_uri.encode('utf-8')).hexdigest()[:16]
