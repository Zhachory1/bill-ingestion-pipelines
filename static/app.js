/**
 * app.js — shared logic for the bill-retrieval chatbot frontend.
 * Handles search (index.html) and chat (chat.html) interactions.
 */

'use strict';

// ---------------------------------------------------------------------------
// Security helpers
// ---------------------------------------------------------------------------

/**
 * Escape text for safe insertion via innerHTML.
 * @param {string} text
 * @returns {string}
 */
function escapeHtml(text) {
    if (text == null) return '';
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/**
 * Validate that a URL uses http: or https: before using it in an href.
 * @param {string} url
 * @returns {string}
 */
function safeUrl(url) {
    if (!url) return '#';
    try {
        const parsed = new URL(url);
        if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
            return url;
        }
    } catch (_) {
        // Not a valid absolute URL — fall through to '#'
    }
    return '#';
}

// ---------------------------------------------------------------------------
// Search page (index.html)
// ---------------------------------------------------------------------------

/**
 * Fetch search results and render them into #results.
 * @param {string} query
 * @param {number} [limit=10]
 */
async function performSearch(query, limit = 10) {
    const resultsEl = document.getElementById('results');
    const loadingEl = document.getElementById('loading');
    const errorEl = document.getElementById('error');

    if (!query || !query.trim()) {
        if (errorEl) {
            errorEl.textContent = 'Please enter a search query.';
            errorEl.hidden = false;
        }
        return;
    }

    // Reset state
    if (errorEl) errorEl.hidden = true;
    if (resultsEl) resultsEl.innerHTML = '';
    if (loadingEl) loadingEl.hidden = false;

    const params = new URLSearchParams({ q: query.trim(), limit: String(limit) });

    try {
        const resp = await fetch('/api/search?' + params.toString());
        if (!resp.ok) {
            throw new Error('Server returned ' + resp.status);
        }
        const data = await resp.json();
        renderResults(data.results || [], resultsEl);
    } catch (err) {
        if (errorEl) {
            errorEl.textContent = 'Search failed: ' + err.message;
            errorEl.hidden = false;
        }
    } finally {
        if (loadingEl) loadingEl.hidden = true;
    }
}

/**
 * Render an array of bill result objects into a container element.
 * @param {Array} results
 * @param {HTMLElement} container
 */
function renderResults(results, container) {
    if (!container) return;

    if (results.length === 0) {
        container.innerHTML = '<p class="no-results">No results found.</p>';
        return;
    }

    const html = results.map(function (bill) {
        const title = escapeHtml(bill.title || 'Untitled');
        const chamber = escapeHtml(bill.chamber || '');
        const date = escapeHtml(bill.introduced_date || '');
        const summary = escapeHtml(
            (bill.summary || '').substring(0, 200) + ((bill.summary || '').length > 200 ? '...' : '')
        );

        // Chat page link — use bill_id path param, never user-supplied raw URL for routing
        const chatHref = '/chat.html?bill_id=' + encodeURIComponent(bill.bill_id || '');

        // External Congress.gov link validated by safeUrl
        const billHref = safeUrl(bill.bill_url);

        return (
            '<div class="result-card">' +
                '<h2 class="result-title">' +
                    '<a href="' + chatHref + '">' + title + '</a>' +
                '</h2>' +
                '<div class="result-meta">' +
                    (chamber ? '<span class="result-chamber">' + chamber + '</span>' : '') +
                    (date ? '<span class="result-date">' + date + '</span>' : '') +
                    (billHref !== '#'
                        ? '<a class="result-external" href="' + escapeHtml(billHref) + '" target="_blank" rel="noopener noreferrer">View on Congress.gov</a>'
                        : '') +
                '</div>' +
                (summary ? '<p class="result-summary">' + summary + '</p>' : '') +
            '</div>'
        );
    }).join('');

    container.innerHTML = html;
}

// ---------------------------------------------------------------------------
// Chat page (chat.html)
// ---------------------------------------------------------------------------

/** In-memory conversation history for the current chat session. */
let _messages = [];
let _currentBillId = null;

/**
 * Initialise the chat page: fetch bill details and wire up the send button.
 * @param {string} billId
 */
async function initChat(billId) {
    const titleEl = document.getElementById('bill-title');
    const errorEl = document.getElementById('error');
    const chatSection = document.getElementById('chat-section');

    if (!billId) {
        if (errorEl) {
            errorEl.textContent = 'No bill_id provided in the URL.';
            errorEl.hidden = false;
        }
        return;
    }

    _currentBillId = billId;
    _messages = [];

    // Fetch bill details
    try {
        const resp = await fetch('/api/bills/' + encodeURIComponent(billId));
        if (!resp.ok) {
            throw new Error('Bill not found (status ' + resp.status + ')');
        }
        const bill = await resp.json();
        if (titleEl) {
            titleEl.textContent = bill.title || billId;
        }
        if (chatSection) chatSection.hidden = false;
    } catch (err) {
        if (errorEl) {
            errorEl.textContent = 'Could not load bill: ' + err.message;
            errorEl.hidden = false;
        }
        return;
    }

    // Wire up send button
    const sendBtn = document.getElementById('send-btn');
    const inputEl = document.getElementById('chat-input');

    if (sendBtn) {
        sendBtn.addEventListener('click', function () {
            _handleSend(billId, inputEl);
        });
    }

    if (inputEl) {
        inputEl.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                _handleSend(billId, inputEl);
            }
        });
    }
}

/**
 * Handle the user clicking Send or pressing Enter.
 * @param {string} billId
 * @param {HTMLElement} inputEl
 */
async function _handleSend(billId, inputEl) {
    const text = inputEl ? inputEl.value.trim() : '';
    if (!text) return;

    // Clear input immediately
    if (inputEl) inputEl.value = '';

    // Append user message to history
    _messages.push({ role: 'user', content: text });
    appendMessage('user', text);

    const sendBtn = document.getElementById('send-btn');
    const loadingEl = document.getElementById('loading');
    const errorEl = document.getElementById('error');

    if (sendBtn) sendBtn.disabled = true;
    if (loadingEl) loadingEl.hidden = false;
    if (errorEl) errorEl.hidden = true;

    try {
        const response = await sendMessage(billId, _messages);
        _messages.push({ role: 'assistant', content: response });
        appendMessage('assistant', response);
    } catch (err) {
        if (errorEl) {
            errorEl.textContent = 'Error: ' + err.message;
            errorEl.hidden = false;
        }
        // Remove the failed user message from history so retry is consistent
        _messages.pop();
    } finally {
        if (sendBtn) sendBtn.disabled = false;
        if (loadingEl) loadingEl.hidden = true;
    }
}

/**
 * Append a message bubble to #chat-history.
 * @param {'user'|'assistant'} role
 * @param {string} content
 */
function appendMessage(role, content) {
    const historyEl = document.getElementById('chat-history');
    if (!historyEl) return;

    const div = document.createElement('div');
    div.className = 'message message-' + escapeHtml(role);
    div.innerHTML = '<span class="message-content">' + escapeHtml(content) + '</span>';
    historyEl.appendChild(div);
    historyEl.scrollTop = historyEl.scrollHeight;
}

/**
 * Send a chat message to the API.
 * @param {string} billId
 * @param {Array<{role: string, content: string}>} messages
 * @returns {Promise<string>} assistant response text
 */
async function sendMessage(billId, messages) {
    const resp = await fetch('/api/chat/' + encodeURIComponent(billId), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: messages }),
    });

    if (!resp.ok) {
        const detail = await resp.text().catch(function () { return resp.statusText; });
        throw new Error('API error ' + resp.status + ': ' + detail);
    }

    const data = await resp.json();
    return data.response || '';
}

// ---------------------------------------------------------------------------
// Page bootstrap
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', function () {
    // ---- Search page ----
    const searchForm = document.getElementById('search-form');
    if (searchForm) {
        searchForm.addEventListener('submit', function (e) {
            e.preventDefault();
            const input = document.getElementById('search-input');
            const query = input ? input.value : '';
            performSearch(query);
        });
    }

    // ---- Chat page ----
    const chatSection = document.getElementById('chat-section');
    if (chatSection !== undefined && document.getElementById('chat-history')) {
        const params = new URLSearchParams(window.location.search);
        const billId = params.get('bill_id') || '';
        initChat(billId);
    }
});
