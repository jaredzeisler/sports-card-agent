"""Tests for database models."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models.database import Base
from src.models.card import (
    Card, Transaction, Listing, ApprovalRequest,
    CardStatus, TransactionType, ApprovalStatus,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def test_create_card(session):
    card = Card(player="Luka Doncic", year=2018, brand="Panini", set_name="Prizm",
                sport="basketball", graded=True, grade=10, purchase_price=150.0)
    session.add(card)
    session.commit()
    assert card.id is not None
    assert card.player == "Luka Doncic"
    assert card.grade == 10


def test_card_default_status(session):
    card = Card(player="Test Player", sport="basketball")
    session.add(card)
    session.commit()
    assert card.status == CardStatus.IN_COLLECTION


def test_create_transaction(session):
    card = Card(player="Test", sport="basketball")
    session.add(card)
    session.commit()
    txn = Transaction(card_id=card.id, transaction_type=TransactionType.BUY, price=100.0)
    session.add(txn)
    session.commit()
    assert txn.id is not None
    assert txn.price == 100.0


def test_create_listing(session):
    listing = Listing(ebay_item_id="12345", title="Test Card", price=50.0)
    session.add(listing)
    session.commit()
    assert listing.purchased is False


def test_create_approval(session):
    approval = ApprovalRequest(action="buy", price=200.0, estimated_fmv=300.0)
    session.add(approval)
    session.commit()
    assert approval.status == ApprovalStatus.PENDING


def test_card_repr(session):
    card = Card(player="LeBron James", year=2003, brand="Topps", sport="basketball",
                graded=True, grade=9)
    assert "LeBron James" in repr(card)
    assert "PSA 9" in repr(card)


def test_card_ungraded_repr(session):
    card = Card(player="LeBron James", year=2003, brand="Topps", sport="basketball")
    assert "PSA" not in repr(card)
