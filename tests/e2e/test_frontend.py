"""Playwright E2E tests for the bill-retrieval chatbot frontend.

Each test mocks API responses at the network level via page.route() so the
live server does not need a populated database.
"""

import json

import pytest
from playwright.sync_api import Page, expect

# ---------------------------------------------------------------------------
# Fake API payloads
# ---------------------------------------------------------------------------

FAKE_SEARCH_RESPONSE = {
    "query": "climate",
    "results": [
        {
            "bill_id": "118-hr-1234",
            "title": "Clean Air Act Amendment",
            "summary": "A bill to improve air quality.",
            "chamber": "House",
            "introduced_date": "2023-01-15",
            "bill_url": "https://www.congress.gov/bill/118th-congress/house-bill/1234",
            "score": 0.95,
        }
    ],
}

FAKE_BILL_RESPONSE = {
    "bill_id": "118-hr-1234",
    "title": "Clean Air Act Amendment",
    "summary": "A bill to improve air quality.",
    "chamber": "House",
    "introduced_date": "2023-01-15",
    "bill_url": "https://www.congress.gov/bill/118th-congress/house-bill/1234",
    "subjects": ["Environment"],
    "sponsors": [],
    "cosponsors": [],
}

FAKE_CHAT_RESPONSE = {
    "bill_id": "118-hr-1234",
    "response": "This bill targets clean air.",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fulfill_json(route, payload):
    """Fulfill a Playwright route with a JSON response."""
    route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps(payload),
    )


# ---------------------------------------------------------------------------
# Search page tests
# ---------------------------------------------------------------------------


def test_search_page_renders(page: Page, live_server):
    """The search page loads and shows the form elements."""
    page.goto(live_server + "/")
    expect(page.locator("#search-form")).to_be_visible()
    expect(page.locator("#search-input")).to_be_visible()


def test_search_returns_results(page: Page, live_server):
    """Submitting a query shows the mocked result card in #results."""
    page.route("**/api/search*", lambda route: _fulfill_json(route, FAKE_SEARCH_RESPONSE))
    page.goto(live_server + "/")
    page.locator("#search-input").fill("climate")
    page.locator("#search-form button[type=submit]").click()
    expect(page.locator("#results")).to_contain_text("Clean Air Act Amendment")


def test_search_empty_query_shows_error(page: Page, live_server):
    """Submitting an empty query shows the #error element."""
    page.goto(live_server + "/")
    # Ensure input is empty, then submit via the button so the JS listener fires.
    page.locator("#search-input").fill("")
    page.locator("#search-form button[type=submit]").click()
    expect(page.locator("#error")).to_be_visible()


def test_result_links_to_chat(page: Page, live_server):
    """Each result card links to chat.html with the correct bill_id query param."""
    page.route("**/api/search*", lambda route: _fulfill_json(route, FAKE_SEARCH_RESPONSE))
    page.goto(live_server + "/")
    page.locator("#search-input").fill("climate")
    page.locator("#search-form button[type=submit]").click()
    # Wait for results to render.
    expect(page.locator("#results")).to_contain_text("Clean Air Act Amendment")
    # The title link should point to the chat page for this bill.
    link = page.locator(".result-title a").first
    href = link.get_attribute("href")
    assert href is not None
    assert "chat.html" in href
    assert "bill_id=118-hr-1234" in href


# ---------------------------------------------------------------------------
# Chat page tests
# ---------------------------------------------------------------------------


def test_chat_page_missing_bill_id(page: Page, live_server):
    """Navigating to chat.html without a bill_id shows #error, hides #chat-section."""
    page.goto(live_server + "/chat.html")
    expect(page.locator("#error")).to_be_visible()
    expect(page.locator("#chat-section")).to_have_attribute("hidden", "")


def test_chat_page_shows_bill_title(page: Page, live_server):
    """With a valid bill_id the chat page shows the bill title and reveals #chat-section."""
    page.route(
        "**/api/bills/118-hr-1234*",
        lambda route: _fulfill_json(route, FAKE_BILL_RESPONSE),
    )
    page.goto(live_server + "/chat.html?bill_id=118-hr-1234")
    expect(page.locator("#bill-title")).to_have_text("Clean Air Act Amendment")
    expect(page.locator("#chat-section")).not_to_have_attribute("hidden", "")


def test_chat_sends_message_and_shows_response(page: Page, live_server):
    """Sending a message appends a user bubble and an assistant bubble."""
    page.route(
        "**/api/bills/118-hr-1234*",
        lambda route: _fulfill_json(route, FAKE_BILL_RESPONSE),
    )
    page.route(
        "**/api/chat/118-hr-1234*",
        lambda route: _fulfill_json(route, FAKE_CHAT_RESPONSE),
    )
    page.goto(live_server + "/chat.html?bill_id=118-hr-1234")
    # Wait for the chat section to be visible before interacting.
    expect(page.locator("#chat-section")).not_to_have_attribute("hidden", "")
    page.locator("#chat-input").fill("What does this bill do?")
    page.locator("#send-btn").click()
    # Both user and assistant messages should appear.
    expect(page.locator(".message")).to_have_count(2)


# ---------------------------------------------------------------------------
# Security tests
# ---------------------------------------------------------------------------


def test_xss_in_title_is_escaped(page: Page, live_server):
    """A title containing a <script> tag must be escaped, not injected into the DOM."""
    xss_payload = "<script>window.__xss=1</script>Malicious Bill"
    xss_search_response = {
        "query": "xss",
        "results": [
            {
                "bill_id": "118-hr-9999",
                "title": xss_payload,
                "summary": "XSS test.",
                "chamber": "House",
                "introduced_date": "2023-01-15",
                "bill_url": "https://www.congress.gov/bill/118th-congress/house-bill/9999",
                "score": 0.99,
            }
        ],
    }
    page.route("**/api/search*", lambda route: _fulfill_json(route, xss_search_response))
    page.goto(live_server + "/")

    # Count <script> tags before the search (baseline — only the app.js tag).
    baseline_count = page.locator("script").count()

    page.locator("#search-input").fill("xss")
    page.locator("#search-form button[type=submit]").click()
    expect(page.locator("#results")).to_contain_text("Malicious Bill")

    # No new <script> tags should have been injected.
    assert page.locator("script").count() == baseline_count

    # The global set by the hypothetical payload must not exist.
    xss_ran = page.evaluate("window.__xss")
    assert xss_ran is None


def test_safe_url_rejects_javascript_protocol(page: Page, live_server):
    """A bill_url with javascript: protocol must not produce a clickable link."""
    js_url_response = {
        "query": "jsurl",
        "results": [
            {
                "bill_id": "118-hr-8888",
                "title": "JS URL Bill",
                "summary": "Test.",
                "chamber": "House",
                "introduced_date": "2023-01-15",
                "bill_url": "javascript:alert(1)",
                "score": 0.9,
            }
        ],
    }
    page.route("**/api/search*", lambda route: _fulfill_json(route, js_url_response))
    page.goto(live_server + "/")
    page.locator("#search-input").fill("jsurl")
    page.locator("#search-form button[type=submit]").click()
    expect(page.locator("#results")).to_contain_text("JS URL Bill")

    # The "View on Congress.gov" link must be absent because safeUrl returns '#'
    # and app.js only renders the anchor when billHref !== '#'.
    external_link = page.locator(".result-external")
    expect(external_link).to_have_count(0)
