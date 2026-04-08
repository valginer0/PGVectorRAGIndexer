import pytest
from datetime import datetime, timezone, timedelta

class TestDocumentStats:
    def test_document_stats_array_agg_deterministic(self, db_manager, sample_embeddings):
        doc_id = "test_doc_stats"
        now = datetime.now(timezone.utc)
        
        t1 = now - timedelta(minutes=10)
        t2 = now - timedelta(minutes=5)
        
        with db_manager.get_cursor() as cursor:
            # We insert the newer chunk first so without ORDER BY it's the first in array_agg
            cursor.execute('''
                INSERT INTO document_chunks (
                    document_id, chunk_index, text_content, source_uri, embedding, metadata, indexed_at, owner_id, visibility
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (doc_id, 1, "newer chunk", "/path/a", sample_embeddings[1], '{"type": "pdf"}', t2, None, 'shared'))
            
            cursor.execute('''
                INSERT INTO document_chunks (
                    document_id, chunk_index, text_content, source_uri, embedding, metadata, indexed_at, owner_id, visibility
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (doc_id, 0, "older chunk", "/path/a", sample_embeddings[0], '{"type": "text"}', t1, None, 'private'))
            
        with db_manager.get_cursor(dict_cursor=True) as cursor:
            cursor.execute("SELECT * FROM document_stats WHERE document_id = %s", (doc_id,))
            stat = cursor.fetchone()
            
        assert stat is not None
        assert stat["source_uri"] == "/path/a"
        assert stat["visibility"] == "private"

