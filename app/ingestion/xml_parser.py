"""Parse BILLSTATUS XML files from the congress/unitedstates corpus into dataclasses."""

from dataclasses import dataclass, field
from pathlib import Path
from loguru import logger
from lxml import etree  # type: ignore


@dataclass
class ParsedSponsor:
    bioguide_id: str
    full_name: str | None
    party: str | None
    state: str | None


@dataclass
class ParsedBill:
    bill_id: str          # e.g. "118-hr-1234"
    congress: int
    bill_type: str        # lowercased: "hr", "s", "hjres", etc.
    bill_number: int
    title: str | None
    summary: str | None
    latest_action: str | None
    latest_action_date: str | None
    last_updated: str | None
    introduced_date: str | None = None
    chamber: str | None = None
    bill_url: str | None = None
    subjects: list[str] = field(default_factory=list)
    sponsors: list[ParsedSponsor] = field(default_factory=list)
    cosponsors: list[ParsedSponsor] = field(default_factory=list)


_BILL_TYPE_URL_MAP = {
    "hr": "house-bill",
    "s": "senate-bill",
    "hres": "house-resolution",
    "sres": "senate-resolution",
    "hjres": "house-joint-resolution",
    "sjres": "senate-joint-resolution",
    "hconres": "house-concurrent-resolution",
    "sconres": "senate-concurrent-resolution",
}


class BillStatusParser:
    @staticmethod
    def parse(xml_path: Path) -> ParsedBill:
        """Parse a BILLSTATUS XML file into a ParsedBill dataclass.

        Raises ValueError if required fields (billType, billNumber, congress) are missing.
        """
        logger.debug(f"Parsing {xml_path}")
        tree = etree.parse(str(xml_path))
        bill = tree.find(".//bill")
        if bill is None:
            raise ValueError(f"No <bill> element found in {xml_path}")

        def req(tag: str) -> str:
            el = bill.find(tag)
            if el is None or not el.text:
                raise ValueError(f"Required field '{tag}' missing in {xml_path}")
            return el.text.strip()

        def opt(tag: str) -> str | None:
            el = bill.find(tag)
            return el.text.strip() if el is not None and el.text else None

        bill_type = req("type").lower()
        bill_number = int(req("number"))
        congress = int(req("congress"))
        bill_id = f"{congress}-{bill_type}-{bill_number}"

        introduced_date = opt("introducedDate")
        chamber = "House" if bill_type.startswith("h") else "Senate" if bill_type.startswith("s") else None
        readable_type = _BILL_TYPE_URL_MAP.get(bill_type, bill_type)
        bill_url = f"https://www.congress.gov/bill/{congress}th-congress/{readable_type}/{bill_number}"

        subjects = [
            el.text.strip()
            for el in bill.findall(".//subjects/legislativeSubjects/item/name")
            if el.text
        ]

        # Latest action: sort items by actionDate, take most recent
        actions = bill.findall(".//actions/item")
        actions_sorted = sorted(
            [(a.findtext("actionDate", ""), a.findtext("text", "")) for a in actions],
            key=lambda x: x[0],
            reverse=True,
        )
        latest_action_date, latest_action = (actions_sorted[0] if actions_sorted else ("", ""))

        def parse_sponsors(tag: str) -> list[ParsedSponsor]:
            return [
                ParsedSponsor(
                    bioguide_id=item.findtext("bioguideId", "").strip(),
                    full_name=item.findtext("fullName"),
                    party=item.findtext("party"),
                    state=item.findtext("state"),
                )
                for item in bill.findall(f".//{tag}/item")
                if item.findtext("bioguideId")
            ]

        return ParsedBill(
            bill_id=bill_id,
            congress=congress,
            bill_type=bill_type,
            bill_number=bill_number,
            title=opt("title"),
            summary=bill.findtext(".//summaries/summary/text"),
            latest_action=latest_action or None,
            latest_action_date=latest_action_date or None,
            last_updated=opt("updateDate"),
            introduced_date=introduced_date,
            chamber=chamber,
            bill_url=bill_url,
            subjects=subjects,
            sponsors=parse_sponsors("sponsors"),
            cosponsors=parse_sponsors("cosponsors"),
        )
