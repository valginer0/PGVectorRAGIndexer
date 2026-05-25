# Local LanceDB Search Beta

Local LanceDB search is an experimental desktop search mode for local text and Markdown folders. It is off by default. When enabled, searches use a local LanceDB index instead of the backend API.

## Enable Local Search

1. Open the desktop app.
2. Open the Settings tab.
3. In the Search panel, enable **Use experimental local text/Markdown search**.
4. Select **Rebuild Local Text/Markdown Index**.
5. Choose the folder to index.
6. Wait for the rebuild to finish. The Settings tab shows the last indexed source and document count.
7. Use the Search tab normally.

To return to the default backend/API search path, disable **Use experimental local text/Markdown search**.

## Supported Files

The beta local index currently supports:

- `.txt`
- `.md`
- `.markdown`

It does not ingest PDF, Word, Excel, PowerPoint, OCR/image, or other binary document formats. Those formats should continue to use the normal backend indexing flow.

## Rebuilds

The local index is built from the selected folder. Selecting **Rebuild Local Text/Markdown Index** again overwrites the current local index with a new one.

Rebuild after:

- adding or removing files in the selected folder
- moving the selected folder
- switching to a different folder
- seeing a stale or missing local index warning

## Known Beta Limits

- The feature is experimental and off by default.
- Local search uses its own local index; it does not search documents uploaded to the backend database.
- Document type and extension filters are not supported in local mode.
- The first local search or rebuild may be slower while the embedding model loads. Later operations in the same desktop session should be faster.
- Search returns one result per source file. Nearby or related documents may also appear when they share strong terms with the query.

## Troubleshooting

**Local Index Not Built**

Open Settings and run **Rebuild Local Text/Markdown Index** before searching in local mode.

**Local Index Needs Rebuild**

The saved index metadata does not match the configured local index path. Rebuild the local text/Markdown index.

**Local Index Missing**

The saved local index folder is no longer present. Rebuild the local text/Markdown index.

**Local Index Busy**

Another local search or rebuild is using the index. Wait for the current operation to finish, then try again.
