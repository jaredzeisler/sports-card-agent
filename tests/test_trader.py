"""Tests for the trading agent."""

import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models.database import Base
from src.models.card import Card, ApprovalRequest, ApprovalStatus, CardStatus


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def test_approval_reject(db_session):
    approval = ApprovalRequest(
        action="buy", price=200.0, estimated_fmv=300.0,
        status=ApprovalStatus.PENDING,
    )
    db_session.add(approval)
    db_session.commit()

    approval.status = ApprovalStatus.REJECTED
    db_session.commit()
    assert approval.status == ApprovalStatus.REJECTED


def test_portfolio_total(db_session):
    cards = [
        Card(player="Player A", sport="basketball", purchase_price=100, status=CardStatus.IN_COLLECTION),
        Card(player="Player B", sport="basketball", purchase_price=200, status=CardStatus.IN_COLLECTION),
        Card(player="Player C", sport="basketball", purchase_price=300, status=CardStatus.SOLD),
    ]
    for c in cards:
        db_session.add(c)
    db_session.commit()

    in_collection = db_session.query(Card).filter(Card.status == CardStatus.IN_COLLECTION).all()
    total = sum(c.purchase_price or 0 for c in in_collection)
    assert total == 300.0


def test_expired_approval(db_session):
    from datetime import datetime, timezone, timedelta
    old = ApprovalRequest(
        action="buy", price=100.0, status=ApprovalStatus.PENDING,
    )
    # Manually set old timestamp
    db_session.add(old)
    db_session.commit()

    old.created_at = datetime.now(timezone.utc) - timedelta(hours=48)
    db_session.commit()

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    expired = db_session.query(ApprovalRequest).filter(
        ApprovalRequest.status == ApprovalStatus.PENDING,
        ApprovalRequest.created_at < cutoff,
    ).all()
    assert len(expired) == 1
