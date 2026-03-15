from dataclasses import dataclass, field
from pathlib import Path
from lxml import etree


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
    sponsors: list[ParsedSponsor] = field(default_factory=list)
    cosponsors: list[ParsedSponsor] = field(default_factory=list)


class BillStatusParser:
    @staticmethod
    def parse(xml_path: Path) -> ParsedBill:
        """Parse a BILLSTATUS XML file into a ParsedBill dataclass.

        Raises ValueError if required fields (billType, billNumber, congress) are missing.
        """
        tree = etree.parse(str(xml_path))
        bill = tree.find(".//bill")

        def req(tag: str) -> str:
            el = bill.find(tag)
            if el is None or not el.text:
                raise ValueError(f"Required field '{tag}' missing in {xml_path}")
            return el.text.strip()

        def opt(tag: str) -> str | None:
            el = bill.find(tag)
            return el.text.strip() if el is not None and el.text else None

        bill_type = req("billType").lower()
        bill_number = int(req("billNumber"))
        congress = int(req("congress"))
        bill_id = f"{congress}-{bill_type}-{bill_number}"

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
            sponsors=parse_sponsors("sponsors"),
            cosponsors=parse_sponsors("cosponsors"),
        )
