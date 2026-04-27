import json
from datetime import datetime
from sqlalchemy import Table, Column, Integer, String, DateTime, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator
from pgvector.sqlalchemy import Vector
from app.db.session import Base
from app.config import settings


class JsonVector(TypeDecorator):
    """SQLite-compatible fallback for Vector columns.

    Under PostgreSQL the underlying Vector type handles serialization natively.
    Under SQLite (in-memory testing) the column is stored as a JSON text string
    and deserialized back to a Python list on retrieval.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            return value  # already serialized (e.g. passed through twice)
        return json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            return json.loads(value)
        return value

# Join tables
bill_sponsors = Table(
    "bill_to_sponsor", Base.metadata,
    Column("bill_id", String, ForeignKey("bills.bill_id"), primary_key=True),
    Column("bioguide_id", String, ForeignKey("sponsors.bioguide_id"), primary_key=True),
)

bill_cosponsors = Table(
    "bill_to_cosponsor", Base.metadata,
    Column("bill_id", String, ForeignKey("bills.bill_id"), primary_key=True),
    Column("bioguide_id", String, ForeignKey("sponsors.bioguide_id"), primary_key=True),
)

bill_subjects = Table(
    "bill_subjects", Base.metadata,
    Column("bill_id", String, ForeignKey("bills.bill_id"), primary_key=True),
    Column("subject_id", Integer, ForeignKey("legislative_subjects.id"), primary_key=True),
)


class Bill(Base):
    __tablename__ = "bills"

    bill_id: Mapped[str] = mapped_column(String, primary_key=True)  # e.g. "118-hr-1234"
    congress: Mapped[int] = mapped_column(Integer, nullable=False)
    bill_type: Mapped[str] = mapped_column(String(10), nullable=False)
    bill_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_action_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_updated: Mapped[str | None] = mapped_column(String(30), nullable=True)
    introduced_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    chamber: Mapped[str | None] = mapped_column(String(10), nullable=True)
    bill_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.EMBEDDING_DIM).with_variant(JsonVector(), "sqlite"),
        nullable=True,
    )

    sponsors: Mapped[list["Sponsor"]] = relationship(
        "Sponsor", secondary=bill_sponsors, back_populates="sponsored_bills"
    )
    cosponsors: Mapped[list["Sponsor"]] = relationship(
        "Sponsor", secondary=bill_cosponsors, back_populates="cosponsored_bills"
    )

    subjects: Mapped[list["LegislativeSubject"]] = relationship(
        "LegislativeSubject", secondary=bill_subjects, back_populates="bills"
    )


class Sponsor(Base):
    __tablename__ = "sponsors"

    bioguide_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    party: Mapped[str | None] = mapped_column(String(5), nullable=True)
    state: Mapped[str | None] = mapped_column(String(5), nullable=True)

    sponsored_bills: Mapped[list["Bill"]] = relationship(
        "Bill", secondary=bill_sponsors, back_populates="sponsors"
    )
    cosponsored_bills: Mapped[list["Bill"]] = relationship(
        "Bill", secondary=bill_cosponsors, back_populates="cosponsors"
    )


class ParseFailure(Base):
    """Dead letter queue: XML files that failed to parse."""
    __tablename__ = "parse_failures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class IngestCheckpoint(Base):
    """Tracks Universe DL progress so it can resume after a crash."""
    __tablename__ = "ingest_checkpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pipeline: Mapped[str] = mapped_column(String(50), nullable=False)  # "universe" or "daily"
    last_processed: Mapped[str | None] = mapped_column(Text, nullable=True)   # directory or git commit SHA
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LegislativeSubject(Base):
    __tablename__ = "legislative_subjects"
    __table_args__ = (UniqueConstraint("name", name="uq_subject_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

    bills: Mapped[list["Bill"]] = relationship(
        "Bill", secondary=bill_subjects, back_populates="subjects"
    )
