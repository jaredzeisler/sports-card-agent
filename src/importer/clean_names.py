"""Clean up player names in the database using Claude Haiku."""

import json
import anthropic

from config.settings import get_settings
from src.models.database import get_session, init_db
from src.models.card import Card


BATCH_SIZE = 30  # cards per Haiku request


def _clean_batch(client: anthropic.Anthropic, cards: list[Card]) -> dict[int, dict]:
    """Send a batch of cards to Haiku and get clean player names back.

    Returns dict mapping card.id -> {"player": str, "sport": str} or {"skip": True}
    """
    lines = []
    for c in cards:
        lines.append(
            f"ID:{c.id} | \"{c.player}\" | year={c.year} brand={c.brand} set={c.set_name} grade={c.grade}"
        )
    card_list = "\n".join(lines)

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4000,
        messages=[{
            "role": "user",
            "content": (
                "You are a sports card data expert. For each card below, extract ONLY the "
                "athlete's real name. Remove card numbers, print runs (/25, /50, etc.), "
                "subset names (Cactus Jack, Downtown, etc.), and other junk.\n\n"
                "If the entry is NOT a sports card (e.g. grading service, supplies, etc.), "
                "set skip=true.\n\n"
                "Also identify the sport: basketball, baseball, football, soccer, hockey, or other.\n\n"
                "Return ONLY a JSON array like:\n"
                '[{"id": 1, "player": "LeBron James", "sport": "basketball"},\n'
                ' {"id": 7, "skip": true}]\n\n'
                f"Cards:\n{card_list}"
            ),
        }],
    )

    text = response.content[0].text.strip()
    # Extract JSON array from response
    start = text.index("[")
    end = text.rindex("]") + 1
    results = json.loads(text[start:end])

    return {r["id"]: r for r in results}


def clean_player_names(dry_run: bool = False) -> dict:
    """Clean all player names in the database.

    Returns dict with: updated (count), skipped (count), not_cards (count), errors (list)
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        return {"updated": 0, "skipped": 0, "not_cards": 0, "errors": ["ANTHROPIC_API_KEY not set"]}

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    init_db()
    session = get_session()
    updated = 0
    skipped = 0
    not_cards = 0
    errors = []

    try:
        cards = session.query(Card).order_by(Card.id).all()
        total = len(cards)
        print(f"Processing {total} cards in batches of {BATCH_SIZE}...")

        for i in range(0, total, BATCH_SIZE):
            batch = cards[i:i + BATCH_SIZE]
            batch_num = (i // BATCH_SIZE) + 1
            total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
            print(f"  Batch {batch_num}/{total_batches} (cards {i+1}-{i+len(batch)})...", end=" ")

            try:
                results = _clean_batch(client, batch)

                for card in batch:
                    r = results.get(card.id)
                    if not r:
                        skipped += 1
                        continue

                    if r.get("skip"):
                        not_cards += 1
                        if not dry_run:
                            card.notes = (card.notes or "") + " [NOT A CARD]"
                        continue

                    new_name = r.get("player", "").strip()
                    if not new_name:
                        skipped += 1
                        continue

                    if not dry_run:
                        card.player = new_name
                        if r.get("sport"):
                            card.sport = r["sport"]

                    updated += 1

                if not dry_run:
                    session.commit()
                print(f"done ({updated} updated so far)")

            except Exception as e:
                errors.append(f"Batch {batch_num}: {str(e)}")
                print(f"ERROR: {e}")

    finally:
        session.close()

    return {"updated": updated, "skipped": skipped, "not_cards": not_cards, "errors": errors}
