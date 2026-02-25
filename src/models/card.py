"""SQLAlchemy models for the sports card trading agent."""

from datetime import datetime, timezone
from sqlalchemy import String, Float, Integer, Boolean, DateTime, Text, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
import enum

from src.models.database import Base


class CardStatus(enum.Enum):
    IN_COLLECTION = "in_collection"
    LISTED = "listed"
    SOLD = "sold"


class TransactionType(enum.Enum):
    BUY = "buy"
    SELL = "sell"


class ApprovalStatus(enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class Card(Base):
    __tablename__ = "cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player: Mapped[str] = mapped_column(String(200), nullable=False)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    set_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    card_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    variation: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sport: Mapped[str] = mapped_column(String(50), default="basketball")
    graded: Mapped[bool] = mapped_column(Boolean, default=False)
    grade: Mapped[float | None] = mapped_column(Float, nullable=True)
    grading_company: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cert_number: Mapped[str | None] = mapped_column(String(50), nullable=True, unique=True)
    purchase_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    purchase_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    purchase_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(
        SAEnum(CardStatus), default=CardStatus.IN_COLLECTION
    )
    current_fmv: Mapped[float | None] = mapped_column(Float, nullable=True)
    fmv_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ebay_item_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self):
        grade_str = f" PSA {self.grade}" if self.graded else ""
        return f"<Card {self.year} {self.brand} {self.player}{grade_str}>"


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    card_id: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_type: Mapped[str] = mapped_column(SAEnum(TransactionType), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    fees: Mapped[float] = mapped_column(Float, default=0.0)
    platform: Mapped[str] = mapped_column(String(50), default="ebay")
    ebay_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self):
        return f"<Transaction {self.transaction_type} card_id={self.card_id} ${self.price}>"


class Listing(Base):
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ebay_item_id: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    seller: Mapped[str | None] = mapped_column(String(100), nullable=True)
    listing_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    player: Mapped[str | None] = mapped_column(String(200), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    set_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    grade: Mapped[float | None] = mapped_column(Float, nullable=True)
    sport: Mapped[str | None] = mapped_column(String(50), nullable=True)
    estimated_fmv: Mapped[float | None] = mapped_column(Float, nullable=True)
    deal_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    purchased: Mapped[bool] = mapped_column(Boolean, default=False)
    scanned_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self):
        return f"<Listing {self.title[:40]} ${self.price}>"


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listing_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    card_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)  # "buy" or "sell"
    price: Mapped[float] = mapped_column(Float, nullable=False)
    estimated_fmv: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        SAEnum(ApprovalStatus), default=ApprovalStatus.PENDING
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self):
        return f"<Approval {self.action} ${self.price} status={self.status}>"
