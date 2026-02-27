"""CLI interface for the sports card trading agent."""

import click
from rich.console import Console
from rich.table import Table

from src.models.database import init_db, get_session
from src.models.card import Card, CardStatus, ApprovalRequest, ApprovalStatus, Listing, Transaction, TransactionType

console = Console()


@click.group()
def cli():
    """Sports Card Trading Agent — autonomous card buying and selling."""
    init_db()


# ── Scan ────────────────────────────────────────────────────────────

@cli.command()
@click.option("--live", is_flag=True, default=False, help="Enable live trading (real purchases)")
def scan(live):
    """Run a single market scan for deals."""
    from src.agent.trader import TradingAgent
    dry_run = not live
    if dry_run:
        console.print("[yellow]DRY RUN mode — no real purchases will be made[/]")
    else:
        console.print("[red bold]LIVE MODE — real purchases enabled![/]")

    agent = TradingAgent()
    deals = agent.run_scan(dry_run=dry_run)

    if not deals:
        console.print("No deals found in this scan.")
        return

    table = Table(title=f"Scan Results — {len(deals)} listings evaluated")
    table.add_column("Player", style="cyan")
    table.add_column("Price", justify="right")
    table.add_column("FMV", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Action", style="bold")
    table.add_column("Profit", justify="right")

    for deal in deals:
        action_color = {"buy": "green", "hold": "yellow", "skip": "dim"}.get(deal["action"], "white")
        profit_color = "green" if deal["estimated_profit"] > 0 else "red"
        table.add_row(
            deal["player"][:30],
            f"${deal['price']:.2f}",
            f"${deal['fmv']:.2f}",
            f"{deal['score']:.0f}",
            f"[{action_color}]{deal['action'].upper()}[/]",
            f"[{profit_color}]${deal['estimated_profit']:.2f}[/]",
        )

    console.print(table)


# ── Run (continuous) ────────────────────────────────────────────────

@cli.command()
@click.option("--live", is_flag=True, default=False, help="Enable live trading")
@click.option("--interval", default=30, help="Minutes between scans")
def run(live, interval):
    """Run the agent continuously, scanning on a schedule."""
    from src.agent.trader import TradingAgent
    from apscheduler.schedulers.blocking import BlockingScheduler

    agent = TradingAgent()
    mode = "LIVE" if live else "DRY RUN"
    console.print(f"[bold]Starting continuous scan ({mode}) every {interval} minutes...[/]")
    console.print("Press Ctrl+C to stop.\n")

    def job():
        console.print(f"\n[dim]Running scan...[/]")
        deals = agent.run_scan(dry_run=not live)
        buy_deals = [d for d in deals if d["action"] == "buy"]
        console.print(f"Found {len(deals)} listings, {len(buy_deals)} buy opportunities.")

    # Run once immediately
    job()

    scheduler = BlockingScheduler()
    scheduler.add_job(job, "interval", minutes=interval)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        console.print("\n[yellow]Agent stopped.[/]")


# ── Inventory ───────────────────────────────────────────────────────

@cli.group()
def inventory():
    """Manage your card inventory."""
    pass


@inventory.command("list")
@click.option("--status", type=click.Choice(["all", "in_collection", "listed", "sold", "returned", "grading_fee"]), default="all")
def inventory_list(status):
    """List cards in your inventory."""
    session = get_session()
    try:
        query = session.query(Card)
        if status != "all":
            query = query.filter(Card.status == CardStatus(status))
        cards = query.order_by(Card.created_at.desc()).all()

        if not cards:
            console.print("No cards in inventory.")
            return

        table = Table(title=f"Inventory ({len(cards)} cards)")
        table.add_column("ID", justify="right")
        table.add_column("Player", style="cyan")
        table.add_column("Year")
        table.add_column("Set")
        table.add_column("Grade")
        table.add_column("Paid", justify="right")
        table.add_column("FMV", justify="right")
        table.add_column("Status")

        for card in cards:
            grade_str = f"PSA {int(card.grade)}" if card.graded and card.grade else "-"
            fmv_str = f"${card.current_fmv:.2f}" if card.current_fmv else "-"
            paid_str = f"${card.purchase_price:.2f}" if card.purchase_price else "-"
            table.add_row(
                str(card.id),
                card.player[:25],
                str(card.year or "-"),
                (card.set_name or "-")[:20],
                grade_str,
                paid_str,
                fmv_str,
                card.status.value if hasattr(card.status, 'value') else str(card.status),
            )

        console.print(table)
    finally:
        session.close()


@inventory.command("add")
@click.option("--player", required=True, help="Player name")
@click.option("--year", type=int, help="Card year")
@click.option("--brand", help="Card brand (e.g. Panini)")
@click.option("--set-name", help="Card set (e.g. Prizm)")
@click.option("--variation", help="Card variation (e.g. Silver, Gold, Refractor)")
@click.option("--card-number", help="Card number (e.g. #280)")
@click.option("--sport", default="basketball", help="Sport")
@click.option("--price", type=float, help="Purchase price")
@click.option("--graded", is_flag=True, help="Is the card graded?")
@click.option("--grade", type=float, help="Numeric grade (e.g. 10)")
@click.option("--cert", help="PSA/BGS cert number")
@click.option("--source", help="Where you bought it")
def inventory_add(player, year, brand, set_name, variation, card_number, sport, price, graded, grade, cert, source):
    """Manually add a card to your inventory."""
    session = get_session()
    try:
        card = Card(
            player=player,
            year=year,
            brand=brand,
            set_name=set_name,
            variation=variation,
            card_number=card_number,
            sport=sport,
            purchase_price=price,
            graded=graded or grade is not None,
            grade=grade,
            grading_company="PSA" if grade else None,
            cert_number=cert,
            purchase_source=source,
            status=CardStatus.IN_COLLECTION,
        )
        session.add(card)
        session.commit()
        console.print(f"[green]Added:[/] {card}")
    finally:
        session.close()


@inventory.command("return")
@click.argument("card_ids", nargs=-1, type=int, required=True)
def inventory_return(card_ids):
    """Mark cards as returned/refunded (removes from invested total)."""
    session = get_session()
    try:
        updated = 0
        for card_id in card_ids:
            card = session.query(Card).filter_by(id=card_id).first()
            if not card:
                console.print(f"[red]Card #{card_id} not found.[/]")
                continue
            if card.status == CardStatus.RETURNED:
                console.print(f"[yellow]Card #{card_id} already marked as returned.[/]")
                continue
            old_status = card.status.value if hasattr(card.status, 'value') else str(card.status)
            card.status = CardStatus.RETURNED
            updated += 1
            console.print(
                f"[green]#{card_id}[/] {card.player[:40]} "
                f"(${card.purchase_price or 0:.2f}) — {old_status} → returned"
            )
        session.commit()
        if updated:
            console.print(f"\n[green]{updated} card(s) marked as returned.[/]")
    finally:
        session.close()


@inventory.command("grading-fee")
@click.argument("card_ids", nargs=-1, type=int, required=True)
def inventory_grading_fee(card_ids):
    """Mark entries as PSA/grading fees (separates from card investment)."""
    session = get_session()
    try:
        updated = 0
        for card_id in card_ids:
            card = session.query(Card).filter_by(id=card_id).first()
            if not card:
                console.print(f"[red]Card #{card_id} not found.[/]")
                continue
            if card.status == CardStatus.GRADING_FEE:
                console.print(f"[yellow]Card #{card_id} already marked as grading fee.[/]")
                continue
            card.status = CardStatus.GRADING_FEE
            updated += 1
            console.print(
                f"[green]#{card_id}[/] {card.player[:40]} (${card.purchase_price or 0:.2f}) → grading_fee"
            )
        session.commit()
        if updated:
            console.print(f"\n[green]{updated} entry/entries marked as grading fees.[/]")
    finally:
        session.close()


@inventory.command("sell")
@click.argument("card_id", type=int)
@click.option("--price", required=True, type=float, help="Hammer / sale price received")
@click.option("--fees", type=float, default=None, help="Platform fees (auto-calculated if omitted)")
@click.option("--platform", type=click.Choice(["goldin", "fanatics", "ebay", "pwcc", "other"]),
              required=True, help="Where the card was sold")
@click.option("--order-id", default=None, help="Lot number or order ID")
@click.option("--notes", default=None, help="Optional notes")
def inventory_sell(card_id, price, fees, platform, order_id, notes):
    """Record a sale (hammer payment from Goldin, Fanatics, etc.)."""
    from datetime import datetime, timezone

    PLATFORM_FEE_RATES = {
        "goldin": 0.20,      # ~20% buyer's premium is on buyer, but seller fees ~0%
        "fanatics": 0.10,    # ~10% seller commission
        "ebay": 0.1625,      # ~16.25% eBay + payment processing
        "pwcc": 0.10,        # ~10% seller commission
        "other": 0.0,
    }

    session = get_session()
    try:
        card = session.query(Card).filter_by(id=card_id).first()
        if not card:
            console.print(f"[red]Card #{card_id} not found.[/]")
            return

        if card.status == CardStatus.SOLD:
            console.print(f"[yellow]Card #{card_id} is already marked as sold.[/]")
            return

        # Calculate fees if not provided
        if fees is None:
            rate = PLATFORM_FEE_RATES.get(platform, 0)
            fees = round(price * rate, 2)
            console.print(f"  [dim]Auto-calculated {platform} fees ({rate:.0%}): ${fees:.2f}[/]")

        net = price - fees
        paid = card.purchase_price or 0
        profit = net - paid

        # Create sell transaction
        txn = Transaction(
            card_id=card.id,
            transaction_type=TransactionType.SELL,
            price=price,
            fees=fees,
            platform=platform,
            ebay_order_id=order_id,
            notes=notes,
            executed_at=datetime.now(timezone.utc),
        )
        session.add(txn)

        # Mark card as sold
        card.status = CardStatus.SOLD
        session.commit()

        profit_color = "green" if profit >= 0 else "red"
        console.print(f"\n[green]Sold:[/] {card.player[:40]}")
        console.print(f"  Platform:   {platform}")
        console.print(f"  Hammer:     ${price:,.2f}")
        console.print(f"  Fees:       ${fees:,.2f}")
        console.print(f"  Net:        ${net:,.2f}")
        console.print(f"  Paid:       ${paid:,.2f}")
        console.print(f"  Profit:     [{profit_color}]${profit:,.2f}[/]")
    finally:
        session.close()


# ── Approvals ───────────────────────────────────────────────────────

@cli.group()
def approvals():
    """Manage trade approval requests."""
    pass


@approvals.command("list")
def approvals_list():
    """Show pending approval requests."""
    session = get_session()
    try:
        pending = (
            session.query(ApprovalRequest)
            .filter(ApprovalRequest.status == ApprovalStatus.PENDING)
            .order_by(ApprovalRequest.created_at.desc())
            .all()
        )

        if not pending:
            console.print("No pending approvals.")
            return

        table = Table(title=f"Pending Approvals ({len(pending)})")
        table.add_column("ID", justify="right")
        table.add_column("Action")
        table.add_column("Price", justify="right")
        table.add_column("FMV", justify="right")
        table.add_column("Est. Profit", justify="right")
        table.add_column("Reason")
        table.add_column("Created")

        for a in pending:
            fmv_str = f"${a.estimated_fmv:.2f}" if a.estimated_fmv else "-"
            profit_str = f"${a.estimated_profit:.2f}" if a.estimated_profit else "-"
            table.add_row(
                str(a.id),
                a.action.upper(),
                f"${a.price:.2f}",
                fmv_str,
                profit_str,
                (a.reason or "-")[:40],
                a.created_at.strftime("%m/%d %H:%M") if a.created_at else "-",
            )

        console.print(table)
    finally:
        session.close()


@approvals.command("approve")
@click.argument("approval_id", type=int)
def approvals_approve(approval_id):
    """Approve a pending trade."""
    from src.agent.trader import TradingAgent
    agent = TradingAgent()
    if agent.execute_approval(approval_id):
        console.print(f"[green]Approval #{approval_id} executed.[/]")
    else:
        console.print(f"[red]Failed to execute approval #{approval_id}.[/]")


@approvals.command("reject")
@click.argument("approval_id", type=int)
def approvals_reject(approval_id):
    """Reject a pending trade."""
    from src.agent.trader import TradingAgent
    agent = TradingAgent()
    if agent.reject_approval(approval_id):
        console.print(f"[yellow]Approval #{approval_id} rejected.[/]")
    else:
        console.print(f"[red]Approval #{approval_id} not found or already resolved.[/]")


# ── Portfolio ───────────────────────────────────────────────────────

@cli.command()
def portfolio():
    """Show portfolio summary and P&L."""
    session = get_session()
    try:
        cards = session.query(Card).all()
        transactions = session.query(Transaction).all()

        in_collection = [
            c for c in cards
            if c.status == CardStatus.IN_COLLECTION
            and not (c.notes and "[NOT A CARD]" in c.notes)
        ]
        sold = [c for c in cards if c.status == CardStatus.SOLD]
        returned = [c for c in cards if c.status == CardStatus.RETURNED]
        grading_fees = [c for c in cards if c.status == CardStatus.GRADING_FEE]
        non_cards = [
            c for c in cards
            if c.status == CardStatus.IN_COLLECTION
            and c.notes and "[NOT A CARD]" in c.notes
        ]

        total_invested = sum(c.purchase_price or 0 for c in in_collection)
        total_fmv = sum(c.current_fmv or c.purchase_price or 0 for c in in_collection)
        total_returned = sum(c.purchase_price or 0 for c in returned)
        total_grading = sum(c.purchase_price or 0 for c in grading_fees)
        total_non_cards = sum(c.purchase_price or 0 for c in non_cards)

        buy_txns = [t for t in transactions if t.transaction_type == TransactionType.BUY]
        sell_txns = [t for t in transactions if t.transaction_type == TransactionType.SELL]
        total_bought = sum(t.price for t in buy_txns)
        total_sold = sum(t.price for t in sell_txns)
        total_fees = sum(t.fees for t in sell_txns)

        realized_pnl = total_sold - total_fees - sum(
            c.purchase_price or 0 for c in sold
        )
        unrealized_pnl = total_fmv - total_invested

        console.print("\n[bold]Portfolio Summary[/]\n")
        console.print(f"  Cards in collection: {len(in_collection)}")
        console.print(f"  Cards sold:          {len(sold)}")
        console.print(f"  Cards returned:      {len(returned):>6}   (${total_returned:>12,.2f})")
        console.print(f"  Grading fees:        {len(grading_fees):>6}   (${total_grading:>12,.2f})")
        if non_cards:
            console.print(f"  Non-card items:      {len(non_cards):>6}   (${total_non_cards:>12,.2f})")
        console.print()
        console.print(f"  Total invested (cards only): ${total_invested:,.2f}")
        console.print(f"  Current FMV:                 ${total_fmv:,.2f}")
        console.print(f"  Unrealized P&L:              ${unrealized_pnl:,.2f}")
        console.print(f"  Realized P&L:                ${realized_pnl:,.2f}")
        console.print()
        console.print(f"  Total spent on eBay:   ${total_bought:,.2f}")
        console.print(f"  Less returns:         -${total_returned:,.2f}")
        console.print(f"  Less grading fees:    -${total_grading:,.2f}")
        console.print(f"  Less non-card items:  -${total_non_cards:,.2f}")
        console.print(f"                         {'─' * 15}")
        net_card_spend = total_bought - total_returned - total_grading - total_non_cards
        console.print(f"  Net card investment:   ${net_card_spend:,.2f}")
        console.print(f"  Total sold:            ${total_sold:,.2f}")
        console.print(f"  Total sell fees:       ${total_fees:,.2f}")
        console.print()
    finally:
        session.close()


# ── Deals ───────────────────────────────────────────────────────────

@cli.command()
@click.option("--limit", default=20, help="Number of recent deals to show")
def deals(limit):
    """Show recent deal opportunities found by the scanner."""
    session = get_session()
    try:
        listings = (
            session.query(Listing)
            .filter(Listing.deal_score.isnot(None))
            .order_by(Listing.deal_score.desc())
            .limit(limit)
            .all()
        )

        if not listings:
            console.print("No deals found yet. Run 'cardagent scan' first.")
            return

        table = Table(title=f"Recent Deals (top {len(listings)})")
        table.add_column("Player", style="cyan")
        table.add_column("Price", justify="right")
        table.add_column("FMV", justify="right")
        table.add_column("Score", justify="right")
        table.add_column("Bought?")
        table.add_column("Scanned")

        for l in listings:
            fmv_str = f"${l.estimated_fmv:.2f}" if l.estimated_fmv else "-"
            table.add_row(
                (l.player or l.title[:25])[:25],
                f"${l.price:.2f}",
                fmv_str,
                f"{l.deal_score:.0f}" if l.deal_score else "-",
                "Yes" if l.purchased else "No",
                l.scanned_at.strftime("%m/%d %H:%M") if l.scanned_at else "-",
            )

        console.print(table)
    finally:
        session.close()


# ── Import ──────────────────────────────────────────────────────────

@cli.group("import")
def import_group():
    """Import cards from files or eBay history."""
    pass


@import_group.command("file")
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--sport", default="basketball", help="Default sport for imported cards")
def import_file_cmd(file_path, sport):
    """Import cards from a CSV or Excel file."""
    from src.importer.xls_import import import_file
    result = import_file(file_path, default_sport=sport)
    console.print(f"[green]Imported:[/] {result['imported']} cards")
    console.print(f"[yellow]Skipped:[/] {result['skipped']} (duplicates or missing data)")
    if result["errors"]:
        console.print(f"[red]Errors:[/]")
        for err in result["errors"]:
            console.print(f"  - {err}")


@import_group.command("ebay")
@click.option("--days", default=365, help="Number of days of history to import")
def import_ebay_cmd(days):
    """Import purchase history from eBay API."""
    from src.importer.ebay_import import import_ebay_purchases
    result = import_ebay_purchases(days=days)
    console.print(f"[green]Imported:[/] {result['imported']} cards")
    console.print(f"[yellow]Skipped:[/] {result['skipped']} (duplicates)")
    if result["errors"]:
        console.print(f"[red]Errors:[/]")
        for err in result["errors"]:
            console.print(f"  - {err}")


@import_group.command("ebay-csv")
@click.argument("file_path", type=click.Path(exists=True))
def import_ebay_csv_cmd(file_path):
    """Import purchase history from an eBay export (CSV, XLS, or XLSX)."""
    from src.importer.ebay_import import import_ebay_csv
    result = import_ebay_csv(file_path)
    console.print(f"[green]Imported:[/] {result['imported']} cards")
    console.print(f"[yellow]Skipped:[/] {result['skipped']} (duplicates or missing data)")
    if result["errors"]:
        console.print(f"[red]Errors:[/]")
        for err in result["errors"][:20]:
            console.print(f"  - {err}")
        if len(result["errors"]) > 20:
            console.print(f"  ... and {len(result['errors']) - 20} more errors")


# ── Targets ─────────────────────────────────────────────────────────

@cli.command()
@click.option("--min-profit", default=15.0, help="Minimum profit % to show")
def targets(min_profit):
    """Find cards in your inventory worth selling now."""
    from src.engine.sale_targets import find_sale_targets
    results = find_sale_targets(min_profit_pct=min_profit)

    if not results:
        console.print("No sale targets found. Add cards to inventory first.")
        return

    table = Table(title=f"Sale Targets ({len(results)} cards)")
    table.add_column("Player", style="cyan")
    table.add_column("Year")
    table.add_column("Grade")
    table.add_column("Paid", justify="right")
    table.add_column("FMV", justify="right")
    table.add_column("Net Profit", justify="right")
    table.add_column("Margin", justify="right")
    table.add_column("Trend")
    table.add_column("Action", style="bold")

    for t in results:
        grade_str = f"PSA {int(t['grade'])}" if t["grade"] else "-"
        trend_color = {"up": "green", "down": "red", "stable": "yellow"}.get(t["trend"], "white")
        action_color = "green" if t["action"] == "sell" else "yellow"
        profit_color = "green" if t["net_profit"] > 0 else "red"
        table.add_row(
            t["player"][:25],
            str(t["year"] or "-"),
            grade_str,
            f"${t['purchase_price']:.2f}",
            f"${t['current_fmv']:.2f}",
            f"[{profit_color}]${t['net_profit']:.2f}[/]",
            f"{t['margin_pct']:.1f}%",
            f"[{trend_color}]{t['trend'].upper()}[/]",
            f"[{action_color}]{t['action'].upper()}[/]",
        )

    console.print(table)


# ── Update FMV ─────────────────────────────────────────────────────

@cli.command("update-fmv")
@click.option("--dry-run", is_flag=True, default=False, help="Don't write to DB")
@click.option("--delay", default=1.0, help="Seconds between API calls")
@click.option("--source", type=click.Choice(["auto", "sportscardspro", "cardhedge", "ebay"]), default="auto",
              help="Pricing source (auto: SportsCardsPro -> Card Hedge -> eBay)")
def update_fmv_cmd(dry_run, delay, source):
    """Update fair market values for all cards in inventory."""
    from src.engine.fmv_update import update_all_fmv
    result = update_all_fmv(dry_run=dry_run, delay=delay, source=source)
    console.print(f"\n[green]Updated:[/] {result['updated']} cards")
    console.print(f"[yellow]No data:[/] {result['no_data']} cards")
    if result["errors"]:
        console.print(f"[red]Errors:[/] {len(result['errors'])}")
        for err in result["errors"][:10]:
            console.print(f"  - {err}")


# ── Flag Mismatches ────────────────────────────────────────────────

@cli.command("flag-mismatches")
@click.option("--min-paid", default=25.0, help="Only flag cards above this purchase price")
@click.option("--low-threshold", default=0.30, help="Flag if FMV < this fraction of paid (default 0.30)")
@click.option("--high-threshold", default=5.0, help="Flag if FMV > this multiple of paid (default 5.0)")
def flag_mismatches_cmd(min_paid, low_threshold, high_threshold):
    """Flag cards where FMV looks wrong (bad API match, missing data, non-cards)."""
    from src.engine.mismatch import flag_mismatches
    result = flag_mismatches(
        min_paid=min_paid,
        low_threshold=low_threshold,
        high_threshold=high_threshold,
    )
    s = result["summary"]
    console.print(f"\n[bold]Mismatch Report[/]  —  {s['total_cards']} cards, "
                  f"[red]{s['flagged']} flagged[/], {s['clean']} clean\n")

    # ── Suspect LOW ───────────────────────────────────────────
    low = result["suspect_low"]
    if low:
        table = Table(title=f"Suspect LOW FMV ({len(low)} cards) — likely wrong API match")
        table.add_column("ID", justify="right", style="dim")
        table.add_column("Player", style="cyan")
        table.add_column("Year")
        table.add_column("Variation", style="yellow")
        table.add_column("Grade")
        table.add_column("Paid", justify="right")
        table.add_column("FMV", justify="right", style="red")
        table.add_column("Diff", justify="right")
        table.add_column("Reason")

        for r in low:
            grade_str = f"PSA {int(r['grade'])}" if r["graded"] and r["grade"] else "Raw"
            table.add_row(
                str(r["id"]),
                r["player"][:25],
                str(r["year"] or "-"),
                (r["variation"] or "-")[:15],
                grade_str,
                f"${r['purchase_price']:.2f}",
                f"${r['current_fmv']:.2f}",
                f"{r['diff_pct']:+.0f}%",
                (r["reason"] or "")[:50],
            )
        console.print(table)
        console.print()

    # ── Suspect HIGH ──────────────────────────────────────────
    high = result["suspect_high"]
    if high:
        table = Table(title=f"Suspect HIGH FMV ({len(high)} cards) — verify these")
        table.add_column("ID", justify="right", style="dim")
        table.add_column("Player", style="cyan")
        table.add_column("Year")
        table.add_column("Variation", style="yellow")
        table.add_column("Grade")
        table.add_column("Paid", justify="right")
        table.add_column("FMV", justify="right", style="green")
        table.add_column("Diff", justify="right")
        table.add_column("Reason")

        for r in high:
            grade_str = f"PSA {int(r['grade'])}" if r["graded"] and r["grade"] else "Raw"
            table.add_row(
                str(r["id"]),
                r["player"][:25],
                str(r["year"] or "-"),
                (r["variation"] or "-")[:15],
                grade_str,
                f"${r['purchase_price']:.2f}",
                f"${r['current_fmv']:.2f}",
                f"{r['diff_pct']:+.0f}%",
                (r["reason"] or "")[:50],
            )
        console.print(table)
        console.print()

    # ── Missing FMV ───────────────────────────────────────────
    missing = result["missing_fmv"]
    if missing:
        table = Table(title=f"Missing FMV ({len(missing)} cards) — no pricing data")
        table.add_column("ID", justify="right", style="dim")
        table.add_column("Player", style="cyan")
        table.add_column("Year")
        table.add_column("Variation", style="yellow")
        table.add_column("Grade")
        table.add_column("Paid", justify="right")

        for r in missing:
            grade_str = f"PSA {int(r['grade'])}" if r["graded"] and r["grade"] else "Raw"
            table.add_row(
                str(r["id"]),
                r["player"][:25],
                str(r["year"] or "-"),
                (r["variation"] or "-")[:15],
                grade_str,
                f"${r['purchase_price']:.2f}",
            )
        console.print(table)
        console.print()

    # ── Non-cards ─────────────────────────────────────────────
    nc = result["non_cards"]
    if nc:
        table = Table(title=f"Non-Card Items ({len(nc)} rows)")
        table.add_column("ID", justify="right", style="dim")
        table.add_column("Description", style="yellow")
        table.add_column("Paid", justify="right")

        for r in nc:
            table.add_row(str(r["id"]), r["player"][:40], f"${r['purchase_price']:.2f}")
        console.print(table)
        console.print()

    if s["flagged"] == 0:
        console.print("[green]All cards look clean![/]")


if __name__ == "__main__":
    cli()
