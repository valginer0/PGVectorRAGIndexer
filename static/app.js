const API_BASE = '';

let currentDocuments = [];
let isDemoMode = false;
let currentQuery = '';

const MODAL_STATE = {
    resolver: null,
    open: false,
};

document.addEventListener('DOMContentLoaded', async () => {
    document.body.classList.add('motion-ready');
    await detectDemoMode();
    initTabs();
    initSearch();
    initUpload();
    initDocuments();
    initConfirmModal();
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

function initTabs() {
    const tabs = document.querySelectorAll('.tab');
    const contents = document.querySelectorAll('.tab-content');

    if (isDemoMode) {
        tabs.forEach((tab) => {
            if (tab.dataset.tab === 'upload') {
                tab.style.display = 'none';
            }
        });

        const banner = createCallout('demo',
            'This demo showcases core search and retrieval. '
            + 'The full application also includes upload and indexing, smart re-indexing, watched folders, '
            + 'desktop click-to-open, auth/SSO controls, document tree navigation, and export/restore. '
            + '<a href="https://www.ragvault.net/" target="_blank" rel="noopener noreferrer">Learn more</a>.');

        const tabsNav = document.querySelector('.tabs');
        tabsNav.parentNode.insertBefore(banner, tabsNav);
    }

    tabs.forEach((tab) => {
        tab.addEventListener('click', () => {
            const targetId = tab.dataset.tab;

            tabs.forEach((t) => t.classList.remove('active'));
            contents.forEach((c) => c.classList.remove('active'));

            tab.classList.add('active');
            document.getElementById(targetId).classList.add('active');

            if (targetId === 'documents') {
                loadDocuments();
            } else if (targetId === 'stats') {
                loadStatistics();
            }
        });
    });
}

async function checkSystemHealth() {
    const indicator = document.getElementById('statusIndicator');
    const statusText = document.getElementById('statusText');

    try {
        const response = await fetch(`${API_BASE}/health`);
        const data = await response.json();

        if (data.status === 'healthy') {
            indicator.classList.remove('error');
            statusText.textContent = 'System healthy';
        } else {
            indicator.classList.add('error');
            statusText.textContent = 'System error';
        }
    } catch (error) {
        indicator.classList.add('error');
        statusText.textContent = 'Connection error';
    }
}

function initSearch() {
    const searchBtn = document.getElementById('searchBtn');
    const searchQuery = document.getElementById('searchQuery');

    searchBtn.addEventListener('click', performSearch);
    searchQuery.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            performSearch();
        }
    });

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
            <div class="empty-state-icon">Search</div>
            <p>Try one of these sample queries:</p>
            <div class="sample-query-list">
                ${sampleQueries.map((q) => `<button class="sample-query-btn" type="button" data-query="${escapeHtml(q)}">${escapeHtml(q)}</button>`).join('')}
            </div>
        </div>
    `;

    resultsContainer.querySelectorAll('.sample-query-btn').forEach((btn) => {
        btn.addEventListener('click', () => {
            const q = btn.dataset.query || '';
            document.getElementById('searchQuery').value = q;
            performSearch();
        });
    });
}

async function performSearch() {
    const query = document.getElementById('searchQuery').value.trim();
    const topK = parseInt(document.getElementById('topK').value, 10);
    const threshold = parseFloat(document.getElementById('threshold').value);
    const method = document.getElementById('searchMethod').value;
    const resultsContainer = document.getElementById('searchResults');

    if (!query) {
        showMessage(resultsContainer, 'Please enter a search query.', 'warning');
        return;
    }

    resultsContainer.innerHTML = '<div class="loading" aria-label="Loading"></div>';

    try {
        const endpoint = method === 'hybrid' ? '/search/hybrid' : '/search';
        const response = await fetch(`${API_BASE}${endpoint}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                query,
                top_k: Number.isFinite(topK) ? topK : 5,
                min_score: Number.isFinite(threshold) ? threshold : 0.3,
            }),
        });

        if (!response.ok) {
            throw new Error(`Request failed (${response.status})`);
        }

        const data = await response.json();
        currentQuery = query;
        displaySearchResults(data.results || []);
    } catch (error) {
        showMessage(resultsContainer, `Search failed: ${escapeHtml(error.message)}`, 'error');
    }
}

function displaySearchResults(results) {
    const container = document.getElementById('searchResults');

    if (results.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">No Match</div>
                <p>No results found. Try adjusting the query or threshold.</p>
            </div>
        `;
        return;
    }

    const desktopHint = isDemoMode
        ? createCalloutHTML('info', 'In the desktop app, you can open matched files directly and jump to highlighted sections.')
        : '';

    container.innerHTML = desktopHint + results.map((result) => {
        const sourceUri = escapeHtml(result.source_uri || 'Unknown source');
        const relevance = Number(result.relevance_score || 0);
        const content = result.text_content || '';
        const snippet = highlightTerms(escapeHtml(extractSnippet(content, currentQuery, 220)), currentQuery);
        const fullText = escapeHtml(content);

        return `
            <article class="result-card">
                <div class="result-header">
                    <div class="result-source">${sourceUri}</div>
                    <div class="result-score">${(relevance * 100).toFixed(1)}%</div>
                </div>
                <div class="result-content">
                    <div class="content-label">Content preview</div>
                    <div class="result-preview">${snippet}</div>
                    ${content.length > 220 ? `<details><summary>Show full text</summary><div class="result-full-text">${fullText}</div></details>` : ''}
                </div>
                <div class="result-meta">
                    <span>Chunk ${escapeHtml(String(result.chunk_index ?? 'N/A'))}</span>
                    <span>Document ${escapeHtml(String(result.document_id ?? 'N/A'))}</span>
                </div>
            </article>
        `;
    }).join('');

    applyStagger(container, '.result-card');
}

function initUpload() {
    const uploadArea = document.getElementById('uploadArea');
    const fileInput = document.getElementById('fileInput');

    if (!uploadArea || !fileInput) {
        return;
    }

    uploadArea.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', (e) => {
        handleFiles(e.target.files);
    });
}

async function handleFiles(files) {
    const progressContainer = document.getElementById('uploadProgress');
    const forceReindex = document.getElementById('forceReindex').checked;
    const customSourceUri = document.getElementById('customSourceUri').value.trim();

    if (!files || files.length === 0) {
        return;
    }

    progressContainer.innerHTML = '';

    for (const file of files) {
        let sourceUri = file.path || file.mozFullPath || file.webkitRelativePath || file.name;
        if (files.length === 1 && customSourceUri) {
            sourceUri = customSourceUri;
        }
        await uploadFile(file, forceReindex, progressContainer, sourceUri);
    }

    if (customSourceUri) {
        document.getElementById('customSourceUri').value = '';
    }
}

async function uploadFile(file, forceReindex, container, customSourceUri = null) {
    const displayName = customSourceUri || file.name;
    const progressId = `progress-${Date.now()}-${Math.random()}`;

    container.insertAdjacentHTML('beforeend', `
        <div class="progress-item" id="${progressId}">
            <div class="progress-header">
                <span>${escapeHtml(displayName)}</span>
                <span class="progress-percent">0%</span>
            </div>
            <div class="progress-bar"><div class="progress-fill"></div></div>
            <div class="progress-status">Uploading...</div>
        </div>
    `);

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
            body: formData,
        });

        let data = {};
        try {
            data = await response.json();
        } catch (e) {
            data = {};
        }

        progressFill.style.width = '100%';
        progressPercent.textContent = '100%';

        if (response.ok) {
            progressStatus.textContent = `Indexed ${data.chunks_indexed || 0} chunks`;
            progressStatus.classList.add('success');
        } else {
            progressStatus.textContent = data.detail || 'Upload failed';
            progressStatus.classList.add('error');
        }
    } catch (error) {
        progressFill.style.width = '100%';
        progressPercent.textContent = '100%';
        progressStatus.textContent = `Error: ${error.message}`;
        progressStatus.classList.add('error');
    }
}

function initDocuments() {
    const refreshBtn = document.getElementById('refreshDocs');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', loadDocuments);
    }
}

async function loadDocuments() {
    const container = document.getElementById('documentsList');
    container.innerHTML = '<div class="loading" aria-label="Loading"></div>';

    try {
        const response = await fetch(`${API_BASE}/documents`);
        if (!response.ok) {
            throw new Error(`Request failed (${response.status})`);
        }

        const data = await response.json();
        const documents = Array.isArray(data) ? data : (data.items || []);
        currentDocuments = documents;
        displayDocuments(documents);
    } catch (error) {
        showMessage(container, `Failed to load documents: ${escapeHtml(error.message)}`, 'error');
    }
}

function displayDocuments(documents) {
    const container = document.getElementById('documentsList');

    if (!documents.length) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">Library</div>
                <p>No documents indexed yet.</p>
            </div>
        `;
        return;
    }

    const desktopHint = isDemoMode
        ? createCalloutHTML('info', 'In the desktop app, click a document to open it and browse indexed chunks.')
        : '';

    container.innerHTML = desktopHint + documents.map((doc) => `
        <article class="document-card stagger-item">
            <div class="document-info">
                <h3>${escapeHtml(doc.source_uri || 'Unknown source')}</h3>
                <div class="document-meta">
                    <span>ID ${escapeHtml(String(doc.document_id ?? 'N/A'))}</span>
                    <span>${escapeHtml(String(doc.chunk_count ?? 0))} chunks</span>
                    <span>${doc.indexed_at ? new Date(doc.indexed_at).toLocaleString() : 'No timestamp'}</span>
                </div>
            </div>
            ${isDemoMode ? '' : `<div class="document-actions"><button class="btn btn-danger" type="button" data-doc-id="${escapeHtml(String(doc.document_id))}">Delete</button></div>`}
        </article>
    `).join('');

    applyStagger(container, '.document-card');

    container.querySelectorAll('[data-doc-id]').forEach((btn) => {
        btn.addEventListener('click', () => {
            deleteDocument(btn.dataset.docId);
        });
    });
}

async function deleteDocument(documentId) {
    const confirmed = await confirmAction(
        'Delete document',
        'This will permanently remove the document and its indexed chunks. Continue?',
        'Delete'
    );

    if (!confirmed) {
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/documents/${encodeURIComponent(documentId)}`, {
            method: 'DELETE',
        });

        if (response.ok) {
            showToast('Document deleted.', 'success');
            loadDocuments();
            return;
        }

        const data = await safeJson(response);
        showToast(data.detail || 'Failed to delete document.', 'error');
    } catch (error) {
        showToast(`Error: ${error.message}`, 'error');
    }
}

async function loadStatistics() {
    const container = document.getElementById('statsContainer');
    container.innerHTML = '<div class="loading" aria-label="Loading"></div>';

    try {
        const response = await fetch(`${API_BASE}/statistics`);
        if (!response.ok) {
            throw new Error(`Request failed (${response.status})`);
        }
        const stats = await response.json();
        displayStatistics(stats);
    } catch (error) {
        showMessage(container, `Failed to load statistics: ${escapeHtml(error.message)}`, 'error');
    }
}

function displayStatistics(stats) {
    const container = document.getElementById('statsContainer');

    container.innerHTML = `
        <div class="stat-card stagger-item">
            <div class="stat-label">Total documents</div>
            <div class="stat-value">${escapeHtml(String(stats.total_documents || 0))}</div>
        </div>
        <div class="stat-card stagger-item">
            <div class="stat-label">Total chunks</div>
            <div class="stat-value">${escapeHtml(String(stats.total_chunks || 0))}</div>
        </div>
        <div class="stat-card stagger-item">
            <div class="stat-label">Database size</div>
            <div class="stat-value">${escapeHtml(formatBytes(stats.database_size_bytes || 0))}</div>
        </div>
        <div class="stat-card stagger-item">
            <div class="stat-label">Embedding model</div>
            <div class="stat-value">${escapeHtml(stats.embedding_model || 'N/A')}</div>
        </div>
    `;

    applyStagger(container, '.stat-card');
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text == null ? '' : String(text);
    return div.innerHTML;
}

function formatBytes(bytes) {
    if (!bytes) {
        return '0 B';
    }

    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.min(Math.floor(Math.log(bytes) / Math.log(k)), sizes.length - 1);
    return `${Math.round((bytes / (k ** i)) * 100) / 100} ${sizes[i]}`;
}

function extractSnippet(text, query, window = 200) {
    if (!text) {
        return '';
    }
    if (!query) {
        return text.length <= window ? text : `${text.slice(0, window).trim()}...`;
    }

    const words = query.toLowerCase().split(/\s+/).filter((w) => w.length >= 2);
    if (!words.length) {
        return text.length <= window ? text : `${text.slice(0, window).trim()}...`;
    }

    const textLower = text.toLowerCase();
    const sorted = [...words].sort((a, b) => b.length - a.length);
    let bestPos = -1;

    for (const word of sorted) {
        const pos = textLower.indexOf(word);
        if (pos !== -1) {
            bestPos = pos;
            break;
        }
    }

    if (bestPos === -1) {
        return text.length <= window ? text : `${text.slice(0, window).trim()}...`;
    }

    const half = Math.floor(window / 2);
    let start = Math.max(0, bestPos - half);
    let end = Math.min(text.length, bestPos + half);

    if (start === 0) {
        end = Math.min(text.length, window);
    } else if (end === text.length) {
        start = Math.max(0, text.length - window);
    }

    const prefix = start > 0 ? '...' : '';
    const suffix = end < text.length ? '...' : '';
    return `${prefix}${text.slice(start, end).trim()}${suffix}`;
}

function highlightTerms(html, query) {
    if (!html || !query) {
        return html;
    }

    const words = query.split(/\s+/).filter((w) => w.length >= 2);
    if (!words.length) {
        return html;
    }

    const pattern = new RegExp(`(${words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'gi');
    return html.replace(pattern, '<mark class="term-highlight">$1</mark>');
}

function showMessage(container, message, type = 'info') {
    container.innerHTML = `<div class="message-card ${escapeHtml(type)}">${message}</div>`;
}

function createCallout(type, html) {
    const wrapper = document.createElement('div');
    wrapper.className = `callout ${type}`;
    wrapper.innerHTML = html;
    return wrapper;
}

function createCalloutHTML(type, html) {
    return `<div class="callout ${type}">${html}</div>`;
}

function showToast(message, type = 'info', timeout = 3500) {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    window.setTimeout(() => {
        toast.remove();
    }, timeout);
}

function applyStagger(container, selector) {
    const items = container.querySelectorAll(selector);
    items.forEach((item, index) => {
        item.classList.add('stagger-item');
        item.style.setProperty('--stagger-index', String(index));
    });
}

function initConfirmModal() {
    const modal = document.getElementById('confirmModal');
    const cancelBtn = document.getElementById('confirmCancel');
    const okBtn = document.getElementById('confirmOk');

    cancelBtn.addEventListener('click', () => closeConfirmModal(false));
    okBtn.addEventListener('click', () => closeConfirmModal(true));

    modal.addEventListener('click', (event) => {
        if (event.target === modal) {
            closeConfirmModal(false);
        }
    });

    document.addEventListener('keydown', (event) => {
        if (MODAL_STATE.open && event.key === 'Escape') {
            closeConfirmModal(false);
        }
    });
}

function confirmAction(title, message, okLabel = 'Confirm') {
    const modal = document.getElementById('confirmModal');
    const titleEl = document.getElementById('confirmTitle');
    const messageEl = document.getElementById('confirmMessage');
    const okBtn = document.getElementById('confirmOk');

    titleEl.textContent = title;
    messageEl.textContent = message;
    okBtn.textContent = okLabel;

    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
    MODAL_STATE.open = true;

    return new Promise((resolve) => {
        MODAL_STATE.resolver = resolve;
    });
}

function closeConfirmModal(value) {
    if (!MODAL_STATE.open) {
        return;
    }

    const modal = document.getElementById('confirmModal');
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');

    MODAL_STATE.open = false;

    if (MODAL_STATE.resolver) {
        MODAL_STATE.resolver(value);
        MODAL_STATE.resolver = null;
    }
}

async function safeJson(response) {
    try {
        return await response.json();
    } catch (e) {
        return {};
    }
}
