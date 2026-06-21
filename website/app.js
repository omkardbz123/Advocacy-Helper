let WORKER_URL = 'https://advocacy-helper-api.omkardbz123.workers.dev';

// Auto-detect local worker for easy testing (only if requested via query parameter)
const urlParams = new URLSearchParams(window.location.search);
if (urlParams.get('local') === 'true' || urlParams.get('local_worker') === 'true') {
    WORKER_URL = 'http://localhost:8787';
}

let currentPlatform = 'youtube'; // or 'instagram'
let currentFilter = null;       // null = all, or 'friendly', 'partial', 'not_friendly'
let currentPage = 1;
const itemsLimit = 12;
let isLoading = false;
let searchQuery = '';

let activeYtFilters = {
    date: 'any',
    scientific: 'any',
    manipulation: 'any',
    method: 'any'
};

function hasActiveYtFilters() {
    return activeYtFilters.date !== 'any' || 
           activeYtFilters.scientific !== 'any' || 
           activeYtFilters.manipulation !== 'any' || 
           activeYtFilters.method !== 'any';
}

function matchesYtFilters(item) {
    const publishedAtStr = item.published_at || item.created_at;
    const publishedDate = publishedAtStr ? new Date(publishedAtStr) : null;
    const now = new Date();
    
    // 1. Upload Date filter
    if (activeYtFilters.date !== 'any' && publishedDate) {
        const diffMs = now - publishedDate;
        const diffDays = diffMs / (1000 * 60 * 60 * 24);
        
        if (activeYtFilters.date === 'today' && diffDays > 1) return false;
        if (activeYtFilters.date === 'week' && diffDays > 7) return false;
        if (activeYtFilters.date === 'month' && diffDays > 30) return false;
        if (activeYtFilters.date === 'year' && diffDays > 365) return false;
    }
    
    // 2. Scientific Grade filter
    if (activeYtFilters.scientific !== 'any') {
        if (item.grade_scientific !== activeYtFilters.scientific) return false;
    }
    
    // 3. Emotional Manipulation filter
    if (activeYtFilters.manipulation !== 'any') {
        if (item.grade_emotional_manipulation !== activeYtFilters.manipulation) return false;
    }
    
    // 4. Grading Method filter
    if (activeYtFilters.method !== 'any') {
        if (item.grading_method !== activeYtFilters.method) return false;
    }
    
    return true;
}

// Fetch content from Worker API
async function fetchContent(page = 1) {
    try {
        isLoading = true;
        const params = new URLSearchParams({ page, limit: itemsLimit });
        if (currentFilter) {
            params.append('filter', currentFilter);
        }
        
        const url = `${WORKER_URL}/api/${currentPlatform}?${params}`;
        console.log(`Fetching feed: ${url}`);
        const resp = await fetch(url);
        if (!resp.ok) {
            throw new Error(`API error: ${resp.status}`);
        }
        return await resp.json();
    } catch (e) {
        console.error('Failed to fetch content:', e);
        return { data: [], total: 0 };
    } finally {
        isLoading = false;
    }
}

// Fetch stats
async function fetchStats() {
    try {
        const url = `${WORKER_URL}/api/stats`;
        const resp = await fetch(url);
        if (resp.ok) {
            const stats = await resp.json();
            updateStatsUI(stats);
        }
    } catch (e) {
        console.error('Failed to fetch stats:', e);
    }
}

// Format relative time (e.g. "3 days ago")
function formatRelativeTime(dateStr) {
    if (!dateStr) return 'N/A';
    try {
        const date = new Date(dateStr);
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMins / 60);
        const diffDays = Math.floor(diffHours / 24);

        if (diffMins < 60) return `${diffMins}m ago`;
        if (diffHours < 24) return `${diffHours}h ago`;
        return `${diffDays}d ago`;
    } catch (e) {
        return 'recently';
    }
}

// Helper to decode HTML entities (e.g. &#39; -> ')
function decodeHTMLEntities(text) {
    if (!text) return '';
    const tempElement = document.createElement('div');
    tempElement.innerHTML = text;
    return tempElement.textContent || tempElement.innerText || '';
}

// Create Card DOM element
// Create Card DOM element
function createCard(item) {
    const card = document.createElement('article');
    card.className = 'social-card';
    
    // Check animal friendly grade for badge styling
    let gradeText = 'Animal Friendly';
    let gradeClass = 'friendly';
    let gradeIcon = '🟢';
    if (item.grade_animal_friendly === 'partial') {
        gradeText = 'Mixed / Neutral';
        gradeClass = 'partial';
        gradeIcon = '🔵';
    } else if (item.grade_animal_friendly === 'not_friendly') {
        gradeText = 'Not Friendly';
        gradeClass = 'not_friendly';
        gradeIcon = '🔴';
    }

    const relativeTime = formatRelativeTime(item.published_at || item.created_at);
    const mediaUrl = item.video_url || item.post_url;
    const rawUsername = item.username || '';
    const cleanUsername = rawUsername.replace(/^@+/, '');
    const author = item.channel_name || (cleanUsername ? `@${cleanUsername}` : 'Creator');
    
    // Generate avatar letter and random background color based on name length
    const initial = author.replace(/[^a-zA-Z0-9]/g, '').substring(0, 1).toUpperCase() || 'C';
    const colors = ['#e94560', '#0f79af', '#0faf62', '#8e44ad', '#f39c12', '#d35400', '#16a085'];
    const colorIndex = author.length % colors.length;
    const avatarBg = colors[colorIndex];

    // Thumbnail and fallbacks
    const fallbackText = currentPlatform === 'youtube' ? 'Video' : 'Post';
    const fallbackImage = `https://placehold.co/600x338/1a1a2e/ffffff?text=${fallbackText}`;

    // Scientific Accuracy badge
    let scientificPill = '';
    if (item.grade_scientific === 'accurate') {
        scientificPill = '<span class="pill accurate">🔬 Accurate</span>';
    } else if (item.grade_scientific === 'inaccurate') {
        scientificPill = '<span class="pill inaccurate">🔬 Inaccurate</span>';
    } else if (item.grade_scientific === 'partial') {
        scientificPill = '<span class="pill partial-sci">🔬 Partial Sci.</span>';
    }

    // Emotional manipulation badge
    const manipulationPill = item.grade_emotional_manipulation === 'yes'
        ? '<span class="pill manipulative">😢 Manipulative</span>'
        : '<span class="pill factual">⚖️ Factual</span>';

    card.innerHTML = `
        <!-- Card Header -->
        <div class="card-header">
            <div class="creator-avatar" style="background-color: ${avatarBg}">${initial}</div>
            <div class="creator-info">
                <div class="creator-name-row">
                    <span class="creator-name">${author}</span>
                    <span class="verified-badge">✓</span>
                </div>
                <span class="post-time">${relativeTime}</span>
            </div>
            <div class="platform-badge-tag ${currentPlatform}">
                ${currentPlatform === 'youtube' ? '▶ YouTube' : '📷 Instagram'}
            </div>
        </div>

        <!-- Card Image/Thumbnail -->
        <div class="card-media-wrapper">
            <img class="card-media-img" src="${item.thumbnail_url || ''}" alt="Post Image" referrerpolicy="no-referrer" onerror="this.onerror=null; this.src='${fallbackImage}';">
        </div>

        <!-- Grade Banner -->
        <div class="grade-banner-stripe ${gradeClass}">
            <span class="grade-icon-dot">${gradeIcon}</span>
            <span class="grade-stripe-text">ADVOCACY ASSESSMENT: <strong>${gradeText.toUpperCase()}</strong></span>
        </div>

        <!-- Card Content Body -->
        <div class="social-card-body">
            <h4 class="post-title">${decodeHTMLEntities(item.title || 'Untitled Discovery')}</h4>
            
            <div class="assessment-callout">
                <div class="callout-header">🛡️ AI Monitor Assessment</div>
                <p class="callout-summary">"${item.summary || 'Critical AI assessment summary pending...'}"</p>
            </div>

            <div class="post-pills">
                ${scientificPill}
                ${manipulationPill}
            </div>

            <a href="${mediaUrl}" target="_blank" class="view-post-button">
                ${currentPlatform === 'youtube' ? '▶ Watch Video on YouTube' : '📷 View Post on Instagram'}
            </a>
        </div>
    `;
    return card;
}

// Search interactions
function handleSearch() {
    const input = document.getElementById('search-input');
    const clearBtn = document.getElementById('search-clear-btn');
    searchQuery = input.value.trim().toLowerCase();
    
    if (searchQuery) {
        clearBtn.style.display = 'block';
    } else {
        clearBtn.style.display = 'none';
    }
    
    currentPage = 1;
    loadFeed(true);
}

function clearSearch() {
    const input = document.getElementById('search-input');
    input.value = '';
    searchQuery = '';
    document.getElementById('search-clear-btn').style.display = 'none';
    currentPage = 1;
    loadFeed(true);
}

// Update Stats UI banner
function updateStatsUI(stats) {
    const pStats = stats[currentPlatform] || { total: 0, friendly: 0, partial: 0, not_friendly: 0 };
    document.getElementById('stats-total').innerText = pStats.total;
    document.getElementById('stats-friendly').innerText = pStats.friendly;
    document.getElementById('stats-partial').innerText = pStats.partial;
    document.getElementById('stats-not-friendly').innerText = pStats.not_friendly;
}

// YouTube style filters UI toggle and handlers
function toggleYtFilterPanel() {
    const panel = document.getElementById('yt-filter-panel');
    const btn = document.getElementById('yt-filter-toggle-btn');
    if (panel.style.display === 'none') {
        panel.style.display = 'block';
        btn.classList.add('active');
    } else {
        panel.style.display = 'none';
        btn.classList.remove('active');
    }
}

function setYtFilter(group, value, elem) {
    activeYtFilters[group] = value;
    
    // Toggle active class inside the clicked list
    const parentList = elem.closest('.yt-filter-list');
    parentList.querySelectorAll('.yt-filter-item').forEach(item => {
        item.classList.remove('active');
    });
    elem.classList.add('active');
    
    currentPage = 1;
    loadFeed(true);
}

// Switch tabs: YouTube or Instagram
async function switchPlatform(platform) {
    if (currentPlatform === platform || isLoading) return;
    
    currentPlatform = platform;
    currentPage = 1;
    
    // Reset filters
    activeYtFilters = { date: 'any', scientific: 'any', manipulation: 'any', method: 'any' };
    document.querySelectorAll('.yt-filter-item').forEach(item => {
        item.classList.toggle('active', item.getAttribute('data-value') === 'any');
    });
    
    // Hide filter panel
    const panel = document.getElementById('yt-filter-panel');
    if (panel) panel.style.display = 'none';
    const btn = document.getElementById('yt-filter-toggle-btn');
    if (btn) btn.classList.remove('active');
    
    // Toggle active classes on tab buttons
    document.getElementById('yt-tab-btn').classList.toggle('active', platform === 'youtube');
    document.getElementById('ig-tab-btn').classList.toggle('active', platform === 'instagram');
    
    // Clear feed and show loader
    const grid = document.getElementById('content-grid');
    grid.innerHTML = '<div class="feed-placeholder">Loading feed...</div>';
    
    // Hide load more button
    document.getElementById('load-more-btn').style.display = 'none';

    // Fetch and render
    await fetchStats();
    await loadFeed(true);
}

// Set Filter: friendly, partial, not_friendly
async function setFilter(filter) {
    if (currentFilter === filter || isLoading) return;
    
    currentFilter = filter;
    currentPage = 1;

    // Toggle active filter button classes
    document.getElementById('filter-all-btn').classList.toggle('active', filter === null);
    document.getElementById('filter-friendly-btn').classList.toggle('active', filter === 'friendly');
    document.getElementById('filter-partial-btn').classList.toggle('active', filter === 'partial');
    document.getElementById('filter-notfriendly-btn').classList.toggle('active', filter === 'not_friendly');

    // Clear feed
    const grid = document.getElementById('content-grid');
    grid.innerHTML = '<div class="feed-placeholder">Filtering feed...</div>';
    
    // Hide load more
    document.getElementById('load-more-btn').style.display = 'none';

    await loadFeed(true);
}

// Load feed items into the grid
async function loadFeed(replace = false) {
    const grid = document.getElementById('content-grid');
    
    let result;
    if (searchQuery || hasActiveYtFilters()) {
        // Fetch a larger page size so we can search/filter client-side thoroughly
        isLoading = true;
        try {
            const params = new URLSearchParams({ page: 1, limit: 1000 });
            if (currentFilter) {
                params.append('filter', currentFilter);
            }
            const url = `${WORKER_URL}/api/${currentPlatform}?${params}`;
            console.log(`Fetching all for search/filter: ${url}`);
            const resp = await fetch(url);
            if (resp.ok) {
                const json = await resp.json();
                // Filter items that match the search query AND the dropdown filters
                const filteredData = json.data.filter(item => {
                    // 1. Search query filter
                    if (searchQuery) {
                        const title = (item.title || '').toLowerCase();
                        const summary = (item.summary || '').toLowerCase();
                        const author = (item.channel_name || item.username || '').toLowerCase();
                        if (!title.includes(searchQuery) && !summary.includes(searchQuery) && !author.includes(searchQuery)) {
                            return false;
                        }
                    }
                    
                    // 2. Dropdown filters
                    return matchesYtFilters(item);
                });
                result = { data: filteredData, total: filteredData.length };
            } else {
                result = { data: [], total: 0 };
            }
        } catch (e) {
            console.error('Failed to search/filter content:', e);
            result = { data: [], total: 0 };
        } finally {
            isLoading = false;
        }
    } else {
        result = await fetchContent(currentPage);
    }
    
    if (replace) {
        grid.innerHTML = '';
    }

    if (result.data && result.data.length > 0) {
        result.data.forEach(item => {
            grid.appendChild(createCard(item));
        });
        
        // Show load more if there are remaining pages (only when not searching/filtering)
        const loadMoreBtn = document.getElementById('load-more-btn');
        if (!searchQuery && !hasActiveYtFilters()) {
            const loadedCount = currentPage * itemsLimit;
            if (loadedCount < result.total) {
                loadMoreBtn.style.display = 'inline-block';
            } else {
                loadMoreBtn.style.display = 'none';
            }
        } else {
            loadMoreBtn.style.display = 'none'; // hide in search/filter mode
        }
    } else {
        if (replace) {
            let msg = 'No graded content found matching filters.';
            if (searchQuery) {
                msg = 'No graded content found matching your search.';
            }
            grid.innerHTML = `<div class="feed-placeholder">${msg}</div>`;
        }
        document.getElementById('load-more-btn').style.display = 'none';
    }
}

// Load more trigger
async function loadMore() {
    if (isLoading) return;
    currentPage++;
    await loadFeed(false);
}

// Init execution
document.addEventListener('DOMContentLoaded', async () => {
    await fetchStats();
    await loadFeed(true);
});

// --- Suggest Video Feature ---
function openSuggestModal() {
    const modal = document.getElementById('suggest-modal');
    const select = document.getElementById('suggest-platform');
    select.value = currentPlatform;
    modal.style.display = 'block';
    document.getElementById('suggest-feedback').style.display = 'none';
    document.getElementById('suggest-url').value = '';
}

function closeSuggestModal() {
    document.getElementById('suggest-modal').style.display = 'none';
}

async function submitVideoSuggestion(e) {
    e.preventDefault();
    const urlInput = document.getElementById('suggest-url');
    const platformInput = document.getElementById('suggest-platform');
    const submitBtn = document.getElementById('suggest-submit-btn');
    const feedback = document.getElementById('suggest-feedback');
    
    const url = urlInput.value.trim();
    const platform = platformInput.value;
    
    if (!url) return;
    
    submitBtn.disabled = true;
    submitBtn.innerText = 'Submitting...';
    feedback.style.display = 'none';
    
    try {
        const response = await fetch(`${WORKER_URL}/api/submissions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, platform })
        });
        
        const result = await response.json();
        
        if (response.ok) {
            feedback.style.display = 'block';
            feedback.style.backgroundColor = 'rgba(76, 175, 80, 0.2)';
            feedback.style.color = '#4CAF50';
            feedback.style.border = '1px solid #4CAF50';
            feedback.innerText = '✅ Video submitted to the grading queue!';
            urlInput.value = '';
            setTimeout(() => {
                closeSuggestModal();
            }, 2000);
        } else {
            throw new Error(result.error || 'Failed to submit video');
        }
    } catch (err) {
        console.error('Submission error:', err);
        feedback.style.display = 'block';
        feedback.style.backgroundColor = 'rgba(244, 67, 54, 0.2)';
        feedback.style.color = '#f44336';
        feedback.style.border = '1px solid #f44336';
        feedback.innerText = '❌ Error: ' + err.message;
    } finally {
        submitBtn.disabled = false;
        submitBtn.innerText = 'Submit to Queue';
    }
}
