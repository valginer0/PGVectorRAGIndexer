// API Base URL
const API_BASE = '';

// State
let currentDocuments = [];
let isDemoMode = false;

// Initialize
document.addEventListener('DOMContentLoaded', async () => {
    await detectDemoMode();
    initTabs();
    initSearch();
    initUpload();
    initDocuments();
    checkSystemHealth();
    loadStatistics();
});

async function detectDemoMode() {
    try {
        const response = await fetch(`${API_BASE}/api`);
        const data = await response.json();
        isDemoMode = !!data.demo;
    } catch (e) {
        isDemoMode = false;
    }
}

// Tab Navigation
function initTabs() {
    const tabs = document.querySelectorAll('.tab');
    const contents = document.querySelectorAll('.tab-content');

    // Hide upload tab in demo mode (uploads are blocked)
    if (isDemoMode) {
        tabs.forEach(tab => {
            if (tab.dataset.tab === 'upload') tab.style.display = 'none';
        });
    }

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const targetId = tab.dataset.tab;

            // Update active states
            tabs.forEach(t => t.classList.remove('active'));
            contents.forEach(c => c.classList.remove('active'));

            tab.classList.add('active');
            document.getElementById(targetId).classList.add('active');

            // Load data for specific tabs
            if (targetId === 'documents') {
                loadDocuments();
            } else if (targetId === 'stats') {
                loadStatistics();
            }
        });
    });
}

// System Health Check
async function checkSystemHealth() {
    try {
        const response = await fetch(`${API_BASE}/health`);
        const data = await response.json();

        const indicator = document.getElementById('statusIndicator');
        const statusText = document.getElementById('statusText');

        if (data.status === 'healthy') {
            indicator.classList.remove('error');
            statusText.textContent = 'System Healthy';
        } else {
            indicator.classList.add('error');
            statusText.textContent = 'System Error';
        }
    } catch (error) {
        const indicator = document.getElementById('statusIndicator');
        const statusText = document.getElementById('statusText');
        indicator.classList.add('error');
        statusText.textContent = 'Connection Error';
    }
}

// Search Functionality
function initSearch() {
    const searchBtn = document.getElementById('searchBtn');
    const searchQuery = document.getElementById('searchQuery');

    searchBtn.addEventListener('click', performSearch);
    searchQuery.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') performSearch();
    });

    // Show sample queries so users know what to search for
    const resultsContainer = document.getElementById('searchResults');
    const sampleQueries = [
        'How does semantic search work?',
        'What is RAG and how does it help LLMs?',
        'How are documents processed and chunked?',
        'What security features are available?',
        'How to deploy and configure the system?',
        'What is HNSW and how does it speed up search?',
    ];
    resultsContainer.innerHTML = `
        <div class="empty-state">
            <div class="empty-state-icon">🔍</div>
            <p>Try one of these sample queries:</p>
            <div style="display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin-top:12px">
                ${sampleQueries.map(q => `<button class="btn" style="font-size:0.85em" onclick="document.getElementById('searchQuery').value='${q}';performSearch()">${q}</button>`).join('')}
            </div>
        </div>
    `;
}

async function performSearch() {
    const query = document.getElementById('searchQuery').value.trim();
    const topK = parseInt(document.getElementById('topK').value);
    const threshold = parseFloat(document.getElementById('threshold').value);
    const method = document.getElementById('searchMethod').value;
    const resultsContainer = document.getElementById('searchResults');

    if (!query) {
        showMessage(resultsContainer, '⚠️ Please enter a search query', 'warning');
        return;
    }

    resultsContainer.innerHTML = '<div class="loading"></div>';

    try {
        const endpoint = method === 'hybrid' ? '/search/hybrid' : '/search';
        const response = await fetch(`${API_BASE}${endpoint}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                query,
                top_k: topK,
                min_score: threshold
            })
        });

        const data = await response.json();
        displaySearchResults(data.results || []);
    } catch (error) {
        showMessage(resultsContainer, `❌ Search failed: ${error.message}`, 'error');
    }
}

function displaySearchResults(results) {
    const container = document.getElementById('searchResults');

    if (results.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">🔍</div>
                <p>No results found. Try adjusting your search query or threshold.</p>
            </div>
        `;
        return;
    }

    container.innerHTML = `
        <div style="background:rgba(99,102,241,0.1);border:1px solid rgba(99,102,241,0.3);border-radius:8px;padding:10px 16px;margin-bottom:16px;font-size:0.9em;color:#a5b4fc">
            💡 In the desktop app, click any result to open the document with the matched section highlighted.
        </div>
    ` + results.map(result => `
        <div class="result-card">
            <div class="result-header">
                <div class="result-source">📄 ${escapeHtml(result.source_uri)}</div>
                <div class="result-score">${(result.relevance_score * 100).toFixed(1)}%</div>
            </div>
            <div class="result-content">${escapeHtml(result.text_content)}</div>
            <div class="result-meta">
                <span>📍 Chunk ${result.chunk_index}</span>
                <span>🆔 ${result.document_id}</span>
            </div>
        </div>
    `).join('');
}

// Upload Functionality
function initUpload() {
    const uploadArea = document.getElementById('uploadArea');
    const fileInput = document.getElementById('fileInput');

    // Click to browse (NO drag & drop)
    uploadArea.addEventListener('click', () => fileInput.click());

    // Handle file selection
    fileInput.addEventListener('change', (e) => {
        handleFiles(e.target.files);
    });
}

async function handleFiles(files) {
    const progressContainer = document.getElementById('uploadProgress');
    const forceReindex = document.getElementById('forceReindex').checked;
    const customSourceUri = document.getElementById('customSourceUri').value.trim();

    progressContainer.innerHTML = '';

    for (const file of files) {
        // Try to get full path from file object (browser-dependent)
        let sourceUri = file.path || file.mozFullPath || file.webkitRelativePath || file.name;

        // If custom source URI is provided for single file, override
        if (files.length === 1 && customSourceUri) {
            sourceUri = customSourceUri;
        }

        await uploadFile(file, forceReindex, progressContainer, sourceUri);
    }

    // Clear custom source URI after upload
    if (customSourceUri) {
        document.getElementById('customSourceUri').value = '';
    }
}

async function uploadFile(file, forceReindex, container, customSourceUri = null) {
    const displayName = customSourceUri || file.name;
    const progressId = `progress-${Date.now()}-${Math.random()}`;
    const progressHtml = `
        <div class="progress-item" id="${progressId}">
            <div class="progress-header">
                <span>📄 ${escapeHtml(displayName)}</span>
                <span class="progress-percent">0%</span>
            </div>
            <div class="progress-bar">
                <div class="progress-fill" style="width: 0%"></div>
            </div>
            <div class="progress-status">Uploading...</div>
        </div>
    `;
    container.insertAdjacentHTML('beforeend', progressHtml);

    const progressItem = document.getElementById(progressId);
    const progressFill = progressItem.querySelector('.progress-fill');
    const progressPercent = progressItem.querySelector('.progress-percent');
    const progressStatus = progressItem.querySelector('.progress-status');

    try {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('force_reindex', forceReindex);
        if (customSourceUri) {
            formData.append('custom_source_uri', customSourceUri);
        }

        const response = await fetch(`${API_BASE}/upload-and-index`, {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        progressFill.style.width = '100%';
        progressPercent.textContent = '100%';

        if (response.ok) {
            progressStatus.textContent = `✅ Indexed ${data.chunks_indexed} chunks`;
            progressStatus.classList.add('success');
        } else {
            progressStatus.textContent = `❌ ${data.detail || 'Upload failed'}`;
            progressStatus.classList.add('error');
        }
    } catch (error) {
        progressFill.style.width = '100%';
        progressPercent.textContent = '100%';
        progressStatus.textContent = `❌ Error: ${error.message}`;
        progressStatus.classList.add('error');
    }
}

// Documents Management
function initDocuments() {
    const refreshBtn = document.getElementById('refreshDocs');
    refreshBtn.addEventListener('click', loadDocuments);
}

async function loadDocuments() {
    const container = document.getElementById('documentsList');
    container.innerHTML = '<div class="loading"></div>';

    try {
        const response = await fetch(`${API_BASE}/documents`);
        const data = await response.json();
        const documents = Array.isArray(data) ? data : (data.items || []);
        currentDocuments = documents;
        displayDocuments(documents);
    } catch (error) {
        showMessage(container, `❌ Failed to load documents: ${error.message}`, 'error');
    }
}

function displayDocuments(documents) {
    const container = document.getElementById('documentsList');

    if (documents.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">📚</div>
                <p>No documents indexed yet. Upload some documents to get started!</p>
            </div>
        `;
        return;
    }

    const desktopHint = isDemoMode ? `
        <div style="background:rgba(99,102,241,0.1);border:1px solid rgba(99,102,241,0.3);border-radius:8px;padding:10px 16px;margin-bottom:16px;font-size:0.9em;color:#a5b4fc">
            💡 In the desktop app, click any document to open it in the editor and browse its indexed chunks.
        </div>
    ` : '';

    container.innerHTML = desktopHint + documents.map(doc => `
        <div class="document-card">
            <div class="document-info">
                <h3>📄 ${escapeHtml(doc.source_uri)}</h3>
                <div class="document-meta">
                    <span>🆔 ${doc.document_id}</span>
                    <span>📊 ${doc.chunk_count} chunks</span>
                    <span>📅 ${new Date(doc.indexed_at).toLocaleString()}</span>
                </div>
            </div>
            ${isDemoMode ? '' : `<div class="document-actions">
                <button class="btn btn-danger" onclick="deleteDocument('${doc.document_id}')">
                    🗑️ Delete
                </button>
            </div>`}
        </div>
    `).join('');
}

async function deleteDocument(documentId) {
    if (!confirm('Are you sure you want to delete this document?')) {
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/documents/${documentId}`, {
            method: 'DELETE'
        });

        if (response.ok) {
            loadDocuments();
        } else {
            const data = await response.json();
            alert(`Failed to delete: ${data.detail}`);
        }
    } catch (error) {
        alert(`Error: ${error.message}`);
    }
}

// Statistics
async function loadStatistics() {
    const container = document.getElementById('statsContainer');
    container.innerHTML = '<div class="loading"></div>';

    try {
        const response = await fetch(`${API_BASE}/statistics`);
        const stats = await response.json();
        displayStatistics(stats);
    } catch (error) {
        showMessage(container, `❌ Failed to load statistics: ${error.message}`, 'error');
    }
}

function displayStatistics(stats) {
    const container = document.getElementById('statsContainer');

    container.innerHTML = `
        <div class="stat-card">
            <div class="stat-label">Total Documents</div>
            <div class="stat-value">${stats.total_documents || 0}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Total Chunks</div>
            <div class="stat-value">${stats.total_chunks || 0}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Database Size</div>
            <div class="stat-value">${formatBytes(stats.database_size_bytes || 0)}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Embedding Model</div>
            <div class="stat-value" style="font-size: 1.2em;">${stats.embedding_model || 'N/A'}</div>
        </div>
    `;
}

// Utility Functions
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

function showMessage(container, message, type) {
    container.innerHTML = `
        <div class="empty-state">
            <p>${message}</p>
        </div>
    `;
}
