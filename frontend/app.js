// --- API Base URL ---
const API_BASE = window.location.origin;

// --- DOM Elements ---
const auditForm = document.getElementById('audit-form');
const siteUrlInput = document.getElementById('site-url');
const runMockBtn = document.getElementById('run-mock-btn');
const startBtn = document.getElementById('start-btn');

// State Panels
const stateLanding = document.getElementById('state-landing');
const stateLoading = document.getElementById('state-loading');
const stateError = document.getElementById('state-error');
const stateResults = document.getElementById('state-results');

// Loader Text
const loaderTitle = document.getElementById('loader-title');
const loaderSubtitle = document.getElementById('loader-subtitle');
const crawlerStatusText = document.getElementById('crawler-status-text');

// Report Meta Elements
const reportUrl = document.getElementById('report-url');
const reportId = document.getElementById('report-id');
const reportDate = document.getElementById('report-date');

// Report Metrics
const metricCrawled = document.getElementById('metric-crawled');
const metricMissingTitle = document.getElementById('metric-missing-title');
const metricMissingDesc = document.getElementById('metric-missing-desc');
const metricMultipleH1 = document.getElementById('metric-multiple-h1');
const metricNoindex = document.getElementById('metric-noindex');
const metricNon200 = document.getElementById('metric-non-200');

// Metric Card Elements (for state coloring)
const cardMissingTitle = document.getElementById('card-missing-title');
const cardMissingDesc = document.getElementById('card-missing-desc');
const cardMultipleH1 = document.getElementById('card-multiple-h1');
const cardNoindex = document.getElementById('card-noindex');
const cardNon200 = document.getElementById('card-non-200');

const pagesListContainer = document.getElementById('pages-list-container');
const crawledPagesBadge = document.getElementById('crawled-pages-badge');
const errorMessage = document.getElementById('error-message');

// Issue explanation and fix map
const ISSUE_REMEDIES = {
    'NON_200_STATUS': 'Page returned a non-200 status code. Check server availability or routing links.',
    'PAGE_SIZE_TOO_LARGE': 'Page size exceeds 2MB. Compress images, scripts, and styles to optimize loading speed.',
    'TITLE_MISSING': 'Title tag is missing. Add a descriptive <title> tag inside the <head> element.',
    'TITLE_TOO_SHORT': 'Title tag is too short (< 30 characters). Expand the title to include target keywords.',
    'TITLE_TOO_LONG': 'Title tag is too long (> 65 characters). Trim the title to avoid ellipsis truncation in search results.',
    'META_DESCRIPTION_MISSING': 'Meta description is missing. Add a <meta name="description" content="..."> tag.',
    'META_DESCRIPTION_TOO_SHORT': 'Meta description is too short (< 70 characters). Add more detail about the page contents.',
    'META_DESCRIPTION_TOO_LONG': 'Meta description is too long (> 160 characters). Shorten the content to fit snippet allowances.',
    'H1_MISSING': 'The page has no H1 heading. Add exactly one primary <h1> tag to state the main topic.',
    'MULTIPLE_H1': 'Multiple H1 tags detected. Consolidate headings so that only one primary <h1> exists.',
    'CANONICAL_MISSING': 'Canonical tag is missing. Add a <link rel="canonical" href="..."> to resolve duplicate indexing.',
    'NOINDEX_PAGE': 'The page declares a noindex instruction. It is blocked from search engine results.'
};

// --- State Transitions ---
function showState(state) {
    // Hide all states
    [stateLanding, stateLoading, stateError, stateResults].forEach(panel => {
        panel.classList.remove('active');
    });

    // Show selected state
    if (state === 'landing') stateLanding.classList.add('active');
    else if (state === 'loading') stateLoading.classList.add('active');
    else if (state === 'error') stateError.classList.add('active');
    else if (state === 'results') stateResults.classList.add('active');
    
    // Refresh icons
    lucide.createIcons();
}

function resetDashboard() {
    siteUrlInput.value = '';
    showState('landing');
}

// --- API Calls & Orchestration ---

// Submit Handler
auditForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    let url = siteUrlInput.value.trim();
    if (!url) return;
    
    await executeAuditFlow(url);
});

// Mock Site Shortcut Handler
runMockBtn.addEventListener('click', async () => {
    const mockUrl = `${API_BASE}/mock-site/homepage`;
    siteUrlInput.value = mockUrl;
    await executeAuditFlow(mockUrl);
});

async function executeAuditFlow(url) {
    // 1. Initial State Transition
    showState('loading');
    loaderTitle.innerText = "Registering Audit Job...";
    loaderSubtitle.innerText = `Preparing to inspect ${url}`;
    crawlerStatusText.innerText = "Queueing audit...";
    
    try {
        // 2. Start Audit Run
        const response = await fetch(`${API_BASE}/api/audit`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ url })
        });
        
        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.detail || 'Failed to start audit job.');
        }
        
        const data = await response.json();
        const auditId = data.audit_id;
        
        // 3. Initiate status polling
        pollAuditResults(auditId);
        
    } catch (err) {
        console.error("Audit start error:", err);
        errorMessage.innerText = err.message || "An unexpected network error occurred.";
        showState('error');
    }
}

// Polling routine
let pollInterval = null;
let pollAttempts = 0;
const MAX_POLL_ATTEMPTS = 90; // 90 seconds safety timeout

function pollAuditResults(auditId) {
    pollAttempts = 0;
    
    if (pollInterval) clearInterval(pollInterval);
    
    pollInterval = setInterval(async () => {
        pollAttempts++;
        if (pollAttempts > MAX_POLL_ATTEMPTS) {
            clearInterval(pollInterval);
            errorMessage.innerText = "Audit timed out. The website takes too long to respond.";
            showState('error');
            return;
        }
        
        try {
            const res = await fetch(`${API_BASE}/api/audit/${auditId}`);
            if (!res.ok) {
                throw new Error("Failed to query audit job progress.");
            }
            
            const auditData = await res.json();
            
            // Handle statuses
            if (auditData.status === 'pending') {
                loaderTitle.innerText = "Analyzing Target Server...";
                loaderSubtitle.innerText = `Connecting to ${auditData.url}`;
                crawlerStatusText.innerText = "Enqueued. Waiting for worker...";
            } else if (auditData.status === 'crawling') {
                loaderTitle.innerText = "Crawling & Auditing Navigation Linkages...";
                loaderSubtitle.innerText = `Analyzing HTML metadata on same-domain pages...`;
                crawlerStatusText.innerText = `Crawl in progress`;
            } else if (auditData.status === 'completed') {
                clearInterval(pollInterval);
                renderAuditReport(auditData);
                showState('results');
            } else if (auditData.status === 'failed') {
                clearInterval(pollInterval);
                errorMessage.innerText = auditData.error_message || "Audit execution encountered a critical crash.";
                showState('error');
            }
            
        } catch (err) {
            console.error("Polling error:", err);
            clearInterval(pollInterval);
            errorMessage.innerText = err.message;
            showState('error');
        }
    }, 1000);
}

// --- UI Rendering ---

function renderAuditReport(audit) {
    // 1. Meta fields
    reportUrl.innerText = audit.url;
    reportId.innerText = audit.audit_id;
    
    // Parse ISO Date
    try {
        const dateObj = new Date(audit.created_at);
        reportDate.innerText = dateObj.toLocaleString();
    } catch {
        reportDate.innerText = audit.created_at;
    }
    
    // 2. Global Metric Cards
    metricCrawled.innerText = audit.pages_crawled;
    
    const sum = audit.summary || {
        missing_title: 0,
        missing_meta_description: 0,
        multiple_h1: 0,
        noindex_pages: 0,
        non_200_pages: 0
    };
    
    metricMissingTitle.innerText = sum.missing_title;
    metricMissingDesc.innerText = sum.missing_meta_description;
    metricMultipleH1.innerText = sum.multiple_h1;
    metricNoindex.innerText = sum.noindex_pages;
    metricNon200.innerText = sum.non_200_pages;
    
    // Set warning/danger state colors
    toggleMetricCardColor(cardMissingTitle, sum.missing_title);
    toggleMetricCardColor(cardMissingDesc, sum.missing_meta_description);
    toggleMetricCardColor(cardMultipleH1, sum.multiple_h1);
    toggleMetricCardColor(cardNoindex, sum.noindex_pages, true); // Noindex is a warning
    toggleMetricCardColor(cardNon200, sum.non_200_pages);
    
    // 3. Render page rows
    pagesListContainer.innerHTML = '';
    crawledPagesBadge.innerText = `${audit.pages_crawled} Page${audit.pages_crawled !== 1 ? 's' : ''}`;
    
    audit.pages.forEach((page, idx) => {
        const hasIssues = page.issues && page.issues.length > 0;
        const statusClass = page.status_code === 200 ? 's-200' : 's-err';
        const issuesBadgeClass = hasIssues ? 'has-issues' : 'clean';
        const issuesBadgeText = hasIssues 
            ? `<i data-lucide="alert-circle" style="width:12px;height:12px;"></i> ${page.issues.length} Issue${page.issues.length > 1 ? 's' : ''}` 
            : `<i data-lucide="check-circle-2" style="width:12px;height:12px;"></i> Clean`;
            
        // Build card HTML
        const card = document.createElement('div');
        card.className = 'page-audit-card';
        card.id = `page-card-${idx}`;
        
        card.innerHTML = `
            <div class="page-summary-row" onclick="togglePageExpand(${idx})">
                <div class="page-info">
                    <span class="status-indicator ${statusClass}">${page.status_code}</span>
                    <span class="page-url-text" title="${page.url}">${page.url}</span>
                </div>
                <div class="page-badges">
                    <span class="issues-badge ${issuesBadgeClass}">${issuesBadgeText}</span>
                    <i data-lucide="chevron-down" class="expand-chevron"></i>
                </div>
            </div>
            
            <div class="page-details-container">
                <div class="details-grid">
                    <div class="detail-item">
                        <span class="detail-lbl">Title Length</span>
                        <span class="detail-val ${getTitleClass(page.title_length, page.issues)}">
                            ${page.title_length !== null ? `${page.title_length} chars` : 'Missing'}
                        </span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-lbl">Meta Description Length</span>
                        <span class="detail-val ${getDescClass(page.meta_description_length, page.issues)}">
                            ${page.meta_description_length !== null ? `${page.meta_description_length} chars` : 'Missing'}
                        </span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-lbl">H1 Header Count</span>
                        <span class="detail-val ${getH1Class(page.h1_count, page.issues)}">
                            ${page.h1_count}
                        </span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-lbl">Canonical Tag</span>
                        <span class="detail-val ${page.canonical_present ? 'ok' : 'bad'}">
                            ${page.canonical_present ? 'Present' : 'Missing'}
                        </span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-lbl">Indexability Status</span>
                        <span class="detail-val ${page.noindex ? 'warn' : 'ok'}">
                            ${page.noindex ? 'Noindex (Blocked)' : 'Indexable'}
                        </span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-lbl">Page Payload Size</span>
                        <span class="detail-val ${page.page_size_kb > 2048 ? 'bad' : 'ok'}">
                            ${page.page_size_kb >= 1024 
                                ? `${(page.page_size_kb / 1024).toFixed(2)} MB` 
                                : `${page.page_size_kb} KB`}
                        </span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-lbl">Internal Links Count</span>
                        <span class="detail-val ok">
                            ${page.internal_links} links
                        </span>
                    </div>
                </div>
                
                <div class="issues-actions-section">
                    <h4>
                        <i data-lucide="check-square"></i> SEO Inspection Checklists
                    </h4>
                    <ul class="action-list">
                        ${renderActionItems(page)}
                    </ul>
                </div>
            </div>
        `;
        
        pagesListContainer.appendChild(card);
    });
    
    // Re-initialize dynamic Lucide icons
    lucide.createIcons();
}

function togglePageExpand(idx) {
    const card = document.getElementById(`page-card-${idx}`);
    if (card) {
        card.classList.toggle('expanded');
    }
}

// Helpers for dynamic styling classes
function toggleMetricCardColor(cardElem, val, isWarningOnly = false) {
    if (!cardElem) return;
    cardElem.classList.remove('warning-state', 'danger-state');
    if (val > 0) {
        if (isWarningOnly) {
            cardElem.classList.add('warning-state');
        } else {
            cardElem.classList.add('danger-state');
        }
    }
}

function getTitleClass(length, issues) {
    if (issues.includes('TITLE_MISSING')) return 'bad';
    if (issues.includes('TITLE_TOO_SHORT') || issues.includes('TITLE_TOO_LONG')) return 'warn';
    return 'ok';
}

function getDescClass(length, issues) {
    if (issues.includes('META_DESCRIPTION_MISSING')) return 'bad';
    if (issues.includes('META_DESCRIPTION_TOO_SHORT') || issues.includes('META_DESCRIPTION_TOO_LONG')) return 'warn';
    return 'ok';
}

function getH1Class(count, issues) {
    if (issues.includes('H1_MISSING')) return 'bad';
    if (issues.includes('MULTIPLE_H1')) return 'warn';
    return 'ok';
}

function renderActionItems(page) {
    // If no issues, show all passed
    if (!page.issues || page.issues.length === 0) {
        return `
            <li class="check-passed"><i data-lucide="check"></i> Page HTTP response status is 200 (OK).</li>
            <li class="check-passed"><i data-lucide="check"></i> Title tag is fully optimized (30-65 chars).</li>
            <li class="check-passed"><i data-lucide="check"></i> Meta description is fully optimized (70-160 chars).</li>
            <li class="check-passed"><i data-lucide="check"></i> Page has exactly one <h1> heading.</li>
            <li class="check-passed"><i data-lucide="check"></i> Canonical tag is correctly specified.</li>
            <li class="check-passed"><i data-lucide="check"></i> Page size is within performance limits.</li>
        `;
    }
    
    // Otherwise, list active recommendations first, then successfully validated rules
    let html = '';
    
    // Active issues
    page.issues.forEach(issue => {
        const text = ISSUE_REMEDIES[issue] || `SEO rule issue detected: ${issue}`;
        html += `<li><i data-lucide="x-circle"></i> <b>Action Needed:</b> ${text}</li>`;
    });
    
    // Passed items
    if (!page.issues.includes('NON_200_STATUS')) {
        html += `<li class="check-passed"><i data-lucide="check"></i> HTTP Response status code is ${page.status_code}.</li>`;
    }
    if (!page.issues.includes('TITLE_MISSING') && !page.issues.includes('TITLE_TOO_SHORT') && !page.issues.includes('TITLE_TOO_LONG')) {
        html += `<li class="check-passed"><i data-lucide="check"></i> Title tag optimized (${page.title_length} chars).</li>`;
    }
    if (!page.issues.includes('META_DESCRIPTION_MISSING') && !page.issues.includes('META_DESCRIPTION_TOO_SHORT') && !page.issues.includes('META_DESCRIPTION_TOO_LONG')) {
        html += `<li class="check-passed"><i data-lucide="check"></i> Meta description optimized (${page.meta_description_length} chars).</li>`;
    }
    if (!page.issues.includes('H1_MISSING') && !page.issues.includes('MULTIPLE_H1')) {
        html += `<li class="check-passed"><i data-lucide="check"></i> Contains exactly 1 <h1> heading.</li>`;
    }
    if (!page.issues.includes('CANONICAL_MISSING')) {
        html += `<li class="check-passed"><i data-lucide="check"></i> Canonical URL tag is set.</li>`;
    }
    if (!page.issues.includes('PAGE_SIZE_TOO_LARGE')) {
        html += `<li class="check-passed"><i data-lucide="check"></i> Payload size is healthy (${page.page_size_kb.toFixed(1)} KB).</li>`;
    }
    
    return html;
}

// Initialize on page load
showState('landing');
