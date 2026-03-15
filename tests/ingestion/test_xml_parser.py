import pytest
from pathlib import Path
from app.ingestion.xml_parser import BillStatusParser, ParsedBill, ParsedSponsor

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
    bad_xml.write_text("<billStatus><bill><billNumber>1</billNumber></bill></billStatus>")
    with pytest.raises(ValueError, match="billType"):
        BillStatusParser.parse(bad_xml)
