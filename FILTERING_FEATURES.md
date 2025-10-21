# Comprehensive Filtering Features - v2.1

## Overview

All three tabs now support comprehensive filtering with metadata discovery from the database.

## Upload Tab

**Document Type Field:**
- Dropdown with common types (resume, policy, report, etc.)
- Editable - you can type custom types
- Optional - leave empty if not needed
- Located in "Options" section between file selection and Force Reindex checkbox

## Search Tab

**Metadata Filters (Optional):**
1. **Document Type**: Dropdown with refresh button (🔄) to load types from database
2. **Custom Metadata**: Key-value pair (e.g., author=John)
3. All filters combined with AND logic

## Manage Tab (Bulk Operations)

**Filter Criteria (All combined with AND):**

1. **Document Type**: 
   - Dropdown with refresh button (🔄)
   - Loads actual types from your database
   - Editable - can add new types

2. **Path/Name Filter**:
   - Supports wildcards: `*` (any characters), `?` (single character)
   - Examples:
     - `*resume*` - any file with "resume" in the path
     - `C:\Projects\*` - all files in C:\Projects
     - `*/2024/*` - all files in any 2024 directory
     - `*draft*.pdf` - all PDF files with "draft" in name

3. **Additional Metadata Filters**:
   - Two key-value pairs
   - Examples:
     - Key: `author`, Value: `John`
     - Key: `department`, Value: `HR`
     - Key: `status`, Value: `obsolete`

## Backend Support

**New Filter Types:**
- `type` - Document type (shortcut for metadata.type)
- `source_uri_like` - SQL LIKE pattern for path/filename
- `metadata.*` - Any custom metadata field

**Metadata Discovery API:**
- `GET /metadata/keys` - List all metadata keys in database
- `GET /metadata/values?key=type` - Get all values for a specific key

## How to Use

### Upload with Type:
1. Select file
2. Choose or enter document type (e.g., "resume")
3. Upload

### Search with Filters:
1. Enter search query
2. Optionally select document type
3. Optionally add metadata filter
4. Search

### Bulk Delete with Filters:
1. Select document type OR enter path pattern OR add metadata
2. Click "Preview" to see what will be deleted
3. Click "Export Backup" (recommended!)
4. Click "Delete" to remove documents
5. Click "Undo" if needed

## Examples

**Delete all drafts:**
- Document Type: `draft`

**Delete all files in a specific folder:**
- Path/Name Filter: `C:\Projects\OldProject\*`

**Delete all resumes from 2023:**
- Document Type: `resume`
- Metadata Key 1: `year`, Value: `2023`

**Delete all obsolete HR documents:**
- Metadata Key 1: `department`, Value: `HR`
- Metadata Key 2: `status`, Value: `obsolete`
