"""SQLAlchemy models for auction bid tracking."""

from datetime import datetime, timezone
from sqlalchemy import String, Float, Integer, Boolean, DateTime, Text, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
import enum

from src.models.database import Base


class BidStatus(enum.Enum):
    WATCHING = "watching"       # Monitoring, no bid placed yet
    BID_PLACED = "bid_placed"   # Proxy/max bid submitted
    OUTBID = "outbid"           # Someone outbid us
    WINNING = "winning"         # Currently the high bidder
    WON = "won"                 # Auction ended, we won
    LOST = "lost"               # Auction ended, we lost
    SKIPPED = "skipped"         # Declined to bid (over FMV ceiling)
    ERROR = "error"             # Something went wrong


class AuctionBid(Base):
    """Tracks bids placed on auction items across platforms."""
    __tablename__ = "auction_bids"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Platform info
    platform: Mapped[str] = mapped_column(String(50), nullable=False)  # "fanatics", "ebay"
    auction_id: Mapped[str] = mapped_column(String(200), nullable=False)  # Platform's auction/item ID
    auction_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Card info
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    player: Mapped[str | None] = mapped_column(String(200), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    set_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    grade: Mapped[float | None] = mapped_column(Float, nullable=True)
    sport: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Pricing
    fmv: Mapped[float | None] = mapped_column(Float, nullable=True)
    fmv_pct: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0.80 or 0.60
    tier: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "tier1" or "tier2"
    max_hammer_bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_all_in: Mapped[float | None] = mapped_column(Float, nullable=True)
    buyers_premium_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Current state
    current_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    our_max_bid: Mapped[float | None] = mapped_column(Float, nullable=True)  # What we actually bid
    bid_count: Mapped[int] = mapped_column(Integer, default=0)  # How many times we've bid
    status: Mapped[str] = mapped_column(
        SAEnum(BidStatus), default=BidStatus.WATCHING
    )

    # Auction timing
    auction_ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Result
    winning_price: Mapped[float | None] = mapped_column(Float, nullable=True)  # Final hammer
    total_paid: Mapped[float | None] = mapped_column(Float, nullable=True)  # Hammer + premium

    # Search criteria that found this auction
    search_query: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Notes
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    last_bid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self):
        return f"<AuctionBid {self.platform} {self.title[:40]} ${self.current_price} [{self.status}]>"


class BidSearchCriteria(Base):
    """Saved search criteria for the autobidder to monitor."""
    __tablename__ = "bid_search_criteria"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # What to search for
    platform: Mapped[str] = mapped_column(String(50), nullable=False)  # "fanatics", "ebay"
    query: Mapped[str] = mapped_column(String(500), nullable=False)
    player: Mapped[str | None] = mapped_column(String(200), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    set_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    min_grade: Mapped[float | None] = mapped_column(Float, nullable=True)
    sport: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Bid limits
    hard_cap: Mapped[float | None] = mapped_column(Float, nullable=True)  # Never bid above this
    override_fmv_pct: Mapped[float | None] = mapped_column(Float, nullable=True)  # Override tier %

    # State
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self):
        return f"<BidSearch {self.platform} '{self.query}' enabled={self.enabled}>"
