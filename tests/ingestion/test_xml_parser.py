import pytest
from pathlib import Path
from app.ingestion.xml_parser import BillStatusParser, ParsedBill, ParsedSponsor, _best_text_url
from lxml import etree

FIXTURE = Path(__file__).parent / "fixtures" / "sample_billstatus.xml"


def test_parses_bill_id():
    result: ParsedBill = BillStatusParser.parse(FIXTURE)
    assert result.bill_id == "118-hr-1234"


def test_parses_bill_metadata():
    result = BillStatusParser.parse(FIXTURE)
    assert result.congress == 118
    assert result.bill_type == "hr"
    assert result.bill_number == 1234
    assert result.title == "A Bill To Test Parsing"


def test_parses_latest_action():
    """Actions must be sorted by date; latest_action is the most recent."""
    result = BillStatusParser.parse(FIXTURE)
    assert result.latest_action == "Passed House"
    assert result.latest_action_date == "2023-01-15"


def test_parses_sponsors():
    result = BillStatusParser.parse(FIXTURE)
    assert len(result.sponsors) == 1
    assert result.sponsors[0].bioguide_id == "A000001"
    assert result.sponsors[0].party == "D"


def test_parses_cosponsors():
    result = BillStatusParser.parse(FIXTURE)
    assert len(result.cosponsors) == 1
    assert result.cosponsors[0].bioguide_id == "B000002"


def test_parses_summary():
    result = BillStatusParser.parse(FIXTURE)
    assert "does a thing" in result.summary


def test_raises_on_missing_required_field(tmp_path):
    """Parser must raise ValueError (not silently produce garbage) if billType is missing."""
    bad_xml = tmp_path / "bad.xml"
    bad_xml.write_text("<billStatus><bill><number>1</number></bill></billStatus>")
    with pytest.raises(ValueError, match="type"):
        BillStatusParser.parse(bad_xml)


def test_raises_when_no_bill_element(tmp_path):
    """Parser must raise ValueError if the XML has no <bill> element at all."""
    bad_xml = tmp_path / "empty.xml"
    bad_xml.write_text("<billStatus></billStatus>")
    with pytest.raises(ValueError, match="No <bill> element"):
        BillStatusParser.parse(bad_xml)


def test_parses_introduced_date():
    result = BillStatusParser.parse(FIXTURE)
    assert result.introduced_date == "2023-01-10"


def test_parses_chamber_house():
    result = BillStatusParser.parse(FIXTURE)  # billType=HR → House
    assert result.chamber == "House"


def test_parses_bill_url():
    result = BillStatusParser.parse(FIXTURE)
    assert result.bill_url == "https://www.congress.gov/bill/118th-congress/house-bill/1234"


def test_parses_subjects():
    result = BillStatusParser.parse(FIXTURE)
    assert sorted(result.subjects) == ["Health care", "Taxation"]


def test_parses_text_url_from_fixture():
    """Parser should extract the best govinfo URL from <textVersions>."""
    result = BillStatusParser.parse(FIXTURE)
    # Fixture has both "Introduced in House" and "Passed House";
    # neither matches _VERSION_PRIORITY so fallback returns the first found.
    assert result.text_url is not None
    assert result.text_url.startswith("https://govinfo.gov/")


def test_text_url_none_when_no_text_versions(tmp_path):
    no_tv_xml = tmp_path / "no_tv.xml"
    no_tv_xml.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<billStatus><bill>
  <type>HR</type><number>1</number><congress>118</congress>
  <title>No Text Versions</title><updateDate>2023-01-01T00:00:00Z</updateDate>
  <sponsors/><cosponsors/><actions/><summaries/>
</bill></billStatus>""")
    result = BillStatusParser.parse(no_tv_xml)
    assert result.text_url is None


# ---------------------------------------------------------------------------
# _best_text_url unit tests
# ---------------------------------------------------------------------------

def _make_bill_el(versions: dict[str, str]):
    """Build a minimal <bill> element with <textVersions> from a {type: url} dict."""
    bill_xml = "<bill><textVersions>"
    for type_name, url in versions.items():
        bill_xml += (
            f"<item><type>{type_name}</type>"
            f"<formats><item><url>{url}</url></item></formats></item>"
        )
    bill_xml += "</textVersions></bill>"
    return etree.fromstring(bill_xml.encode())


def test_best_text_url_prefers_enrolled():
    el = _make_bill_el({
        "Introduced in House": "https://example.com/ih.xml",
        "Enrolled Bill": "https://example.com/enr.xml",
    })
    assert _best_text_url(el) == "https://example.com/enr.xml"


def test_best_text_url_falls_back_to_introduced():
    el = _make_bill_el({"Introduced in Senate": "https://example.com/is.xml"})
    assert _best_text_url(el) == "https://example.com/is.xml"


def test_best_text_url_returns_none_when_no_text_versions():
    el = etree.fromstring(b"<bill></bill>")
    assert _best_text_url(el) is None


def test_best_text_url_returns_none_when_no_urls():
    el = etree.fromstring(b"<bill><textVersions><item><type>Introduced in House</type><formats/></item></textVersions></bill>")
    assert _best_text_url(el) is None


def test_best_text_url_fallback_when_no_priority_match():
    el = _make_bill_el({"Some Unknown Version": "https://example.com/unknown.xml"})
    assert _best_text_url(el) == "https://example.com/unknown.xml"


def test_chamber_senate(tmp_path):
    senate_xml = tmp_path / "senate.xml"
    senate_xml.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<billStatus><bill>
  <type>S</type><number>5</number><congress>118</congress>
  <title>A Senate Bill</title><updateDate>2023-01-01T00:00:00Z</updateDate>
  <sponsors/><cosponsors/><actions/><summaries/>
</bill></billStatus>""")
    result = BillStatusParser.parse(senate_xml)
    assert result.chamber == "Senate"
    assert result.bill_url == "https://www.congress.gov/bill/118th-congress/senate-bill/5"
