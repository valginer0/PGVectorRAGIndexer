"""
Migration script from v1 to v2.

This script helps migrate existing v1 databases to the new v2 schema
while preserving all existing data.
"""

import logging
import argparse
import sys
from datetime import datetime

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

from config import get_config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MigrationError(Exception):
    """Exception for migration errors."""
    pass


class DatabaseMigrator:
    """Handles database migration from v1 to v2."""
    
    def __init__(self):
        """Initialize migrator."""
        self.config = get_config()
        self.conn = None
    
    def connect(self):
        """Connect to database."""
        try:
            self.conn = psycopg2.connect(
                host=self.config.database.host,
                port=self.config.database.port,
                dbname=self.config.database.name,
                user=self.config.database.user,
                password=self.config.database.password
            )
            self.conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            logger.info("Connected to database")
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            raise MigrationError(f"Connection failed: {e}")
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")
    
    def check_v1_schema(self) -> bool:
        """Check if v1 schema exists."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'document_chunks'
            );
        """)
        exists = cursor.fetchone()[0]
        cursor.close()
        return exists
    
    def check_v2_schema(self) -> bool:
        """Check if v2 schema already exists."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.columns 
                WHERE table_name = 'document_chunks' 
                AND column_name = 'metadata'
            );
        """)
        has_metadata = cursor.fetchone()[0]
        cursor.close()
        return has_metadata
    
    def backup_data(self) -> str:
        """Create backup of existing data."""
        backup_table = f"document_chunks_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        cursor = self.conn.cursor()
        cursor.execute(f"""
            CREATE TABLE {backup_table} AS 
            SELECT * FROM document_chunks;
        """)
        
        cursor.execute(f"SELECT COUNT(*) FROM {backup_table};")
        count = cursor.fetchone()[0]
        cursor.close()
        
        logger.info(f"Backed up {count} rows to {backup_table}")
        return backup_table
    
    def add_new_columns(self):
        """Add new columns from v2 schema."""
        cursor = self.conn.cursor()
        
        # Add metadata column if not exists
        cursor.execute("""
            ALTER TABLE document_chunks 
            ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';
        """)
        logger.info("Added metadata column")
        
        # Add indexed_at column if not exists
        cursor.execute("""
            ALTER TABLE document_chunks 
            ADD COLUMN IF NOT EXISTS indexed_at TIMESTAMP DEFAULT NOW();
        """)
        logger.info("Added indexed_at column")
        
        # Add updated_at column if not exists
        cursor.execute("""
            ALTER TABLE document_chunks 
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();
        """)
        logger.info("Added updated_at column")
        
        cursor.close()
    
    def add_constraints(self):
        """Add new constraints."""
        cursor = self.conn.cursor()
        
        # Add unique constraint if not exists
        cursor.execute("""
            DO $$ 
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint 
                    WHERE conname = 'document_chunks_document_id_chunk_index_key'
                ) THEN
                    ALTER TABLE document_chunks 
                    ADD CONSTRAINT document_chunks_document_id_chunk_index_key 
                    UNIQUE (document_id, chunk_index);
                END IF;
            END $$;
        """)
        logger.info("Added unique constraint")
        
        cursor.close()
    
    def create_indexes(self):
        """Create new indexes."""
        cursor = self.conn.cursor()
        
        # Create indexes if not exist
        indexes = [
            ("idx_chunks_document_id", "document_id"),
            ("idx_chunks_source_uri", "source_uri"),
            ("idx_chunks_indexed_at", "indexed_at DESC"),
        ]
        
        for idx_name, idx_column in indexes:
            cursor.execute(f"""
                CREATE INDEX IF NOT EXISTS {idx_name} 
                ON document_chunks({idx_column});
            """)
            logger.info(f"Created index: {idx_name}")
        
        # Create GIN index for full-text search
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_text_search 
            ON document_chunks USING gin(to_tsvector('english', text_content));
        """)
        logger.info("Created full-text search index")
        
        # Create GIN index for metadata
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_metadata 
            ON document_chunks USING gin(metadata);
        """)
        logger.info("Created metadata index")
        
        cursor.close()
    
    def create_trigger(self):
        """Create updated_at trigger."""
        cursor = self.conn.cursor()
        
        # Create function
        cursor.execute("""
            CREATE OR REPLACE FUNCTION update_updated_at_column()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = NOW();
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """)
        
        # Create trigger
        cursor.execute("""
            DROP TRIGGER IF EXISTS update_document_chunks_updated_at ON document_chunks;
            CREATE TRIGGER update_document_chunks_updated_at
                BEFORE UPDATE ON document_chunks
                FOR EACH ROW
                EXECUTE FUNCTION update_updated_at_column();
        """)
        logger.info("Created updated_at trigger")
        
        cursor.close()
    
    def create_views(self):
        """Create new views."""
        cursor = self.conn.cursor()
        
        cursor.execute("""
            CREATE OR REPLACE VIEW document_stats AS
            SELECT 
                document_id,
                source_uri,
                COUNT(*) as chunk_count,
                MIN(indexed_at) as first_indexed,
                MAX(updated_at) as last_updated,
                jsonb_object_agg(
                    COALESCE(metadata->>'file_type', 'unknown'),
                    1
                ) as metadata_summary
            FROM document_chunks
            GROUP BY document_id, source_uri;
        """)
        logger.info("Created document_stats view")
        
        cursor.close()
    
    def enable_extensions(self):
        """Enable required extensions."""
        cursor = self.conn.cursor()
        
        # Enable pg_trgm for full-text search
        cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        logger.info("Enabled pg_trgm extension")
        
        cursor.close()
    
    def verify_migration(self) -> dict:
        """Verify migration was successful."""
        cursor = self.conn.cursor()
        
        # Check columns
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'document_chunks'
            ORDER BY ordinal_position;
        """)
        columns = [row[0] for row in cursor.fetchall()]
        
        # Check indexes
        cursor.execute("""
            SELECT indexname 
            FROM pg_indexes 
            WHERE tablename = 'document_chunks';
        """)
        indexes = [row[0] for row in cursor.fetchall()]
        
        # Check row count
        cursor.execute("SELECT COUNT(*) FROM document_chunks;")
        row_count = cursor.fetchone()[0]
        
        cursor.close()
        
        return {
            'columns': columns,
            'indexes': indexes,
            'row_count': row_count
        }
    
    def migrate(self, create_backup: bool = True):
        """
        Perform full migration.
        
        Args:
            create_backup: Whether to create backup before migration
        """
        logger.info("Starting migration from v1 to v2...")
        
        try:
            # Check if v1 schema exists
            if not self.check_v1_schema():
                raise MigrationError("v1 schema not found. Nothing to migrate.")
            
            # Check if already migrated
            if self.check_v2_schema():
                logger.warning("v2 schema already exists. Migration may have already been performed.")
                response = input("Continue anyway? (y/n): ")
                if response.lower() != 'y':
                    logger.info("Migration cancelled")
                    return
            
            # Create backup
            backup_table = None
            if create_backup:
                backup_table = self.backup_data()
            
            # Perform migration steps
            logger.info("Step 1: Enabling extensions...")
            self.enable_extensions()
            
            logger.info("Step 2: Adding new columns...")
            self.add_new_columns()
            
            logger.info("Step 3: Adding constraints...")
            self.add_constraints()
            
            logger.info("Step 4: Creating indexes...")
            self.create_indexes()
            
            logger.info("Step 5: Creating triggers...")
            self.create_trigger()
            
            logger.info("Step 6: Creating views...")
            self.create_views()
            
            # Verify migration
            logger.info("Verifying migration...")
            verification = self.verify_migration()
            
            logger.info("\n" + "="*60)
            logger.info("Migration completed successfully!")
            logger.info("="*60)
            logger.info(f"Columns: {len(verification['columns'])}")
            logger.info(f"Indexes: {len(verification['indexes'])}")
            logger.info(f"Rows: {verification['row_count']}")
            
            if backup_table:
                logger.info(f"\nBackup table: {backup_table}")
                logger.info("You can drop the backup table once you've verified everything works:")
                logger.info(f"  DROP TABLE {backup_table};")
            
            logger.info("\nNext steps:")
            logger.info("1. Test the new v2 CLI: python indexer_v2.py stats")
            logger.info("2. Test search: python retriever_v2.py 'your query'")
            logger.info("3. Start API: python api.py")
            
        except Exception as e:
            logger.error(f"Migration failed: {e}")
            raise


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Migrate PGVectorRAGIndexer from v1 to v2',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This script will:
1. Create a backup of your existing data
2. Add new columns (metadata, indexed_at, updated_at)
3. Create new indexes for better performance
4. Add constraints and triggers
5. Create helper views

Your existing data will be preserved.
        """
    )
    
    parser.add_argument(
        '--no-backup',
        action='store_true',
        help='Skip backup creation (not recommended)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Check migration status without making changes'
    )
    
    args = parser.parse_args()
    
    migrator = DatabaseMigrator()
    
    try:
        migrator.connect()
        
        if args.dry_run:
            logger.info("Dry run mode - checking migration status...")
            
            has_v1 = migrator.check_v1_schema()
            has_v2 = migrator.check_v2_schema()
            
            logger.info(f"v1 schema exists: {has_v1}")
            logger.info(f"v2 schema exists: {has_v2}")
            
            if has_v1 and not has_v2:
                logger.info("✓ Ready for migration")
            elif has_v1 and has_v2:
                logger.info("⚠ Already migrated or partially migrated")
            else:
                logger.info("✗ No v1 schema found")
        else:
            migrator.migrate(create_backup=not args.no_backup)
        
    except KeyboardInterrupt:
        logger.info("\nMigration cancelled by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        sys.exit(1)
    finally:
        migrator.close()


if __name__ == '__main__':
    main()
