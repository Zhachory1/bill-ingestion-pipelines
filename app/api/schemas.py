"""Pydantic response models for the bill retrieval API."""

from pydantic import BaseModel


class SponsorOut(BaseModel):
    bioguide_id: str
    full_name: str | None
    party: str | None
    state: str | None

    model_config = {"from_attributes": True}


class BillOut(BaseModel):
    bill_id: str
    congress: int
    bill_type: str
    bill_number: int
    title: str | None
    summary: str | None
    latest_action: str | None
    latest_action_date: str | None
    introduced_date: str | None
    chamber: str | None
    bill_url: str | None
    subjects: list[str]
    sponsors: list[SponsorOut]
    cosponsors: list[SponsorOut]

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_bill(cls, bill) -> "BillOut":
        """Construct from ORM Bill; subjects must be extracted by name since they are ORM objects."""
        return cls(
            bill_id=bill.bill_id,
            congress=bill.congress,
            bill_type=bill.bill_type,
            bill_number=bill.bill_number,
            title=bill.title,
            summary=bill.summary,
            latest_action=bill.latest_action,
            latest_action_date=bill.latest_action_date,
            introduced_date=bill.introduced_date,
            chamber=bill.chamber,
            bill_url=bill.bill_url,
            subjects=[s.name for s in bill.subjects],
            sponsors=bill.sponsors,
            cosponsors=bill.cosponsors,
        )


class BillTextOut(BaseModel):
    bill_id: str
    title: str | None
    text: str


class BillSummaryOut(BaseModel):
    bill_id: str
    title: str | None
    summary: str | None
    chamber: str | None
    introduced_date: str | None
    bill_url: str | None
    score: float


class SearchResponse(BaseModel):
    query: str
    results: list[BillSummaryOut]
