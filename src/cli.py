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
@click.option("--platform", type=click.Choice(["ebay", "fanatics", "psa_direct", "pwcc", "other"]),
              required=True, help="Where the card was sold")
@click.option("--order-id", default=None, help="Lot number or order ID")
@click.option("--notes", default=None, help="Optional notes")
def inventory_sell(card_id, price, fees, platform, order_id, notes):
    """Record a sale (hammer payment from Goldin, Fanatics, etc.)."""
    from datetime import datetime, timezone

    PLATFORM_FEE_RATES = {
        "ebay": 0.1625,      # ~16.25% eBay + payment processing
        "fanatics": 0.0,     # Auction fees vary per lot
        "psa_direct": 0.0,   # Direct sales to PSA affiliates
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
@click.option("--source", type=click.Choice(["auto", "sportscardspro", "cardladder", "cardhedge", "ebay"]), default="auto",
              help="Pricing source (auto: SportsCardsPro -> CardLadder -> Card Hedge)")
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


# ── eBay Selling ───────────────────────────────────────────────────

@cli.group()
def ebay():
    """eBay selling commands — list cards, manage prices, handle offers."""
    pass


@ebay.command("auth")
@click.option("--port", default=8471, help="Local port for OAuth callback")
def ebay_auth(port):
    """Authenticate with eBay (opens browser for OAuth consent)."""
    from src.api.ebay_auth import start_auth_flow
    try:
        tokens = start_auth_flow(port=port)
        console.print(f"[green]Authenticated successfully![/]")
        console.print(f"  Access token expires in {tokens['expires_in'] // 3600}h")
        console.print(f"  Refresh token saved for long-term use")
    except Exception as e:
        console.print(f"[red]Authentication failed:[/] {e}")


@ebay.command("list-card")
@click.argument("card_id", type=int)
@click.option("--price", type=float, help="Listing price (auto-calculated if omitted)")
@click.option("--margin", type=float, default=0.20, help="Target profit margin (default 20%)")
@click.option("--best-offer/--no-best-offer", default=True, help="Enable best offer")
@click.option("--dry-run", is_flag=True, default=False, help="Show what would be listed without posting")
@click.option("--test", is_flag=True, default=False, help="Use Test Auctions category per eBay test listing policy")
def ebay_list_card(card_id, price, margin, best_offer, dry_run, test):
    """List a card from inventory on eBay."""
    from src.api.ebay import EbayClient
    from src.engine.listing_builder import build_card_listing, calculate_list_price

    session = get_session()
    try:
        card = session.query(Card).filter_by(id=card_id).first()
        if not card:
            console.print(f"[red]Card #{card_id} not found.[/]")
            return

        if card.status == CardStatus.SOLD:
            console.print(f"[red]Card #{card_id} is already sold.[/]")
            return

        if card.status == CardStatus.LISTED:
            console.print(f"[yellow]Card #{card_id} is already listed on eBay.[/]")
            return

        # Build listing data
        card_data = build_card_listing(card)
        pricing = calculate_list_price(card, target_margin=margin)

        list_price = price or pricing["list_price"]
        est_fees = round(list_price * 0.1625, 2)
        est_net = round(list_price - est_fees, 2)
        est_profit = round(est_net - (card.purchase_price or 0), 2)

        # Show preview
        console.print(f"\n[bold]Listing Preview[/]")
        console.print(f"  Title:        {card_data['title']}")
        console.print(f"  Condition:    {card_data['condition_description'][:60] or card_data['condition']}")
        console.print(f"  Cost basis:   ${card.purchase_price or 0:,.2f}")
        console.print(f"  List price:   ${list_price:,.2f}")
        console.print(f"  Est. fees:    ${est_fees:,.2f}")
        console.print(f"  Est. net:     ${est_net:,.2f}")
        profit_color = "green" if est_profit >= 0 else "red"
        console.print(f"  Est. profit:  [{profit_color}]${est_profit:,.2f}[/]")

        if best_offer:
            console.print(f"  Auto-accept:  ${pricing['auto_accept']:,.2f}")
            console.print(f"  Auto-decline: ${pricing['auto_decline']:,.2f}")

        # Aspects
        console.print(f"\n  [dim]Item Specifics:[/]")
        for key, vals in card_data["aspects"].items():
            console.print(f"    {key}: {', '.join(vals)}")

        if dry_run:
            console.print(f"\n[yellow]DRY RUN — listing not created.[/]")
            return

        # Create the listing
        ebay_client = EbayClient()
        sku = f"card-{card.id}"

        result = ebay_client.create_listing(
            card_data=card_data,
            price=list_price,
            sku=sku,
            best_offer=best_offer,
            auto_accept_price=pricing["auto_accept"] if best_offer else None,
            auto_decline_price=pricing["auto_decline"] if best_offer else None,
            test_listing=test,
        )

        # Update card status
        card.status = CardStatus.LISTED
        card.ebay_item_id = result.get("listingId")
        session.commit()

        console.print(f"\n[green]Listed on eBay![/]")
        console.print(f"  Listing ID: {result.get('listingId')}")
        console.print(f"  SKU: {sku}")

    finally:
        session.close()


@ebay.command("bulk-list")
@click.option("--min-profit", type=float, default=15.0, help="Min profit % to list")
@click.option("--margin", type=float, default=0.20, help="Target profit margin")
@click.option("--limit", type=int, default=10, help="Max cards to list")
@click.option("--dry-run", is_flag=True, default=True, help="Preview only (default)")
@click.option("--live", is_flag=True, default=False, help="Actually create listings")
@click.option("--test", is_flag=True, default=False, help="Use Test Auctions category per eBay test listing policy")
def ebay_bulk_list(min_profit, margin, limit, dry_run, live, test):
    """List multiple cards from inventory based on profit targets."""
    from src.engine.listing_builder import build_card_listing, calculate_list_price

    if live:
        dry_run = False

    session = get_session()
    try:
        cards = (
            session.query(Card)
            .filter(Card.status == CardStatus.IN_COLLECTION)
            .filter(Card.purchase_price > 0)
            .filter(Card.current_fmv.isnot(None))
            .all()
        )

        candidates = []
        for card in cards:
            if card.notes and "[NOT A CARD]" in card.notes:
                continue
            pricing = calculate_list_price(card, target_margin=margin)
            if pricing["cost_basis"] > 0:
                margin_pct = (pricing["est_profit"] / pricing["cost_basis"]) * 100
                if margin_pct >= min_profit:
                    candidates.append((card, pricing, margin_pct))

        candidates.sort(key=lambda x: x[2], reverse=True)
        candidates = candidates[:limit]

        if not candidates:
            console.print("No cards meet the profit threshold for listing.")
            return

        table = Table(title=f"{'[DRY RUN] ' if dry_run else ''}Bulk Listing ({len(candidates)} cards)")
        table.add_column("ID", justify="right")
        table.add_column("Player", style="cyan")
        table.add_column("Grade")
        table.add_column("Cost", justify="right")
        table.add_column("List Price", justify="right")
        table.add_column("Est. Net", justify="right")
        table.add_column("Profit", justify="right")
        table.add_column("Margin", justify="right")

        for card, pricing, margin_pct in candidates:
            grade_str = f"PSA {int(card.grade)}" if card.graded and card.grade else "-"
            profit_color = "green" if pricing["est_profit"] >= 0 else "red"
            table.add_row(
                str(card.id),
                card.player[:25],
                grade_str,
                f"${pricing['cost_basis']:,.2f}",
                f"${pricing['list_price']:,.2f}",
                f"${pricing['est_net']:,.2f}",
                f"[{profit_color}]${pricing['est_profit']:,.2f}[/]",
                f"{margin_pct:.1f}%",
            )

        console.print(table)

        if dry_run:
            console.print(f"\n[yellow]DRY RUN — run with --live to create listings.[/]")
            return

        # Actually list them
        from src.api.ebay import EbayClient
        ebay_client = EbayClient()
        listed = 0
        errors = 0

        for card, pricing, _ in candidates:
            try:
                card_data = build_card_listing(card)
                sku = f"card-{card.id}"
                result = ebay_client.create_listing(
                    card_data=card_data,
                    price=pricing["list_price"],
                    sku=sku,
                    best_offer=True,
                    auto_accept_price=pricing["auto_accept"],
                    auto_decline_price=pricing["auto_decline"],
                    test_listing=test,
                )
                card.status = CardStatus.LISTED
                card.ebay_item_id = result.get("listingId")
                listed += 1
                console.print(f"  [green]Listed:[/] {card.player[:30]} @ ${pricing['list_price']:,.2f}")
            except Exception as e:
                errors += 1
                console.print(f"  [red]Failed:[/] {card.player[:30]} — {e}")

        session.commit()
        console.print(f"\n[green]{listed} listed[/], [red]{errors} errors[/]")

    finally:
        session.close()


@ebay.command("active")
def ebay_active():
    """Show cards currently listed on eBay."""
    session = get_session()
    try:
        listed = (
            session.query(Card)
            .filter(Card.status == CardStatus.LISTED)
            .order_by(Card.updated_at.desc())
            .all()
        )

        if not listed:
            console.print("No cards currently listed on eBay.")
            return

        table = Table(title=f"Active eBay Listings ({len(listed)})")
        table.add_column("ID", justify="right")
        table.add_column("Player", style="cyan")
        table.add_column("Year")
        table.add_column("Grade")
        table.add_column("Cost", justify="right")
        table.add_column("FMV", justify="right")
        table.add_column("eBay Item ID")

        for card in listed:
            grade_str = f"PSA {int(card.grade)}" if card.graded and card.grade else "-"
            fmv_str = f"${card.current_fmv:,.2f}" if card.current_fmv else "-"
            table.add_row(
                str(card.id),
                card.player[:25],
                str(card.year or "-"),
                grade_str,
                f"${card.purchase_price or 0:,.2f}",
                fmv_str,
                card.ebay_item_id or "-",
            )

        console.print(table)
    finally:
        session.close()


@ebay.command("update-price")
@click.argument("card_id", type=int)
@click.option("--price", required=True, type=float, help="New listing price")
def ebay_update_price(card_id, price):
    """Update the price on an active eBay listing."""
    from src.api.ebay import EbayClient

    session = get_session()
    try:
        card = session.query(Card).filter_by(id=card_id).first()
        if not card:
            console.print(f"[red]Card #{card_id} not found.[/]")
            return
        if card.status != CardStatus.LISTED:
            console.print(f"[red]Card #{card_id} is not currently listed (status: {card.status}).[/]")
            return

        ebay_client = EbayClient()
        sku = f"card-{card.id}"
        offers = ebay_client.get_offers(sku=sku)

        if not offers:
            console.print(f"[red]No eBay offer found for SKU {sku}.[/]")
            return

        offer_id = offers[0]["offerId"]
        ebay_client.update_offer_price(offer_id, price)

        est_fees = round(price * 0.1625, 2)
        est_net = round(price - est_fees, 2)
        est_profit = round(est_net - (card.purchase_price or 0), 2)
        profit_color = "green" if est_profit >= 0 else "red"

        console.print(f"[green]Price updated![/]")
        console.print(f"  {card.player[:40]}")
        console.print(f"  New price:   ${price:,.2f}")
        console.print(f"  Est. net:    ${est_net:,.2f}")
        console.print(f"  Est. profit: [{profit_color}]${est_profit:,.2f}[/]")

    finally:
        session.close()


@ebay.command("end-listing")
@click.argument("card_id", type=int)
def ebay_end_listing(card_id):
    """End (withdraw) an active eBay listing."""
    from src.api.ebay import EbayClient

    session = get_session()
    try:
        card = session.query(Card).filter_by(id=card_id).first()
        if not card:
            console.print(f"[red]Card #{card_id} not found.[/]")
            return
        if card.status != CardStatus.LISTED:
            console.print(f"[red]Card #{card_id} is not currently listed.[/]")
            return

        ebay_client = EbayClient()
        sku = f"card-{card.id}"
        offers = ebay_client.get_offers(sku=sku)

        if not offers:
            console.print(f"[yellow]No eBay offer found for SKU {sku}. Updating status only.[/]")
        else:
            for offer in offers:
                try:
                    ebay_client.withdraw_offer(offer["offerId"])
                except Exception as e:
                    console.print(f"[yellow]Could not withdraw offer {offer['offerId']}: {e}[/]")

        card.status = CardStatus.IN_COLLECTION
        card.ebay_item_id = None
        session.commit()
        console.print(f"[green]Listing ended.[/] {card.player[:40]} returned to collection.")

    finally:
        session.close()


@ebay.command("policies")
def ebay_policies():
    """Show your eBay seller policies (shipping, returns, payment)."""
    from src.api.ebay import EbayClient

    ebay_client = EbayClient()

    console.print("\n[bold]Fulfillment (Shipping) Policies[/]")
    try:
        for p in ebay_client.get_fulfillment_policies():
            console.print(f"  ID: {p['fulfillmentPolicyId']}  Name: {p.get('name', 'N/A')}")
    except Exception as e:
        console.print(f"  [red]{e}[/]")

    console.print("\n[bold]Return Policies[/]")
    try:
        for p in ebay_client.get_return_policies():
            console.print(f"  ID: {p['returnPolicyId']}  Name: {p.get('name', 'N/A')}")
    except Exception as e:
        console.print(f"  [red]{e}[/]")

    console.print("\n[bold]Payment Policies[/]")
    try:
        for p in ebay_client.get_payment_policies():
            console.print(f"  ID: {p['paymentPolicyId']}  Name: {p.get('name', 'N/A')}")
    except Exception as e:
        console.print(f"  [red]{e}[/]")


@ebay.command("sync-sold")
@click.option("--days", default=30, help="Days of order history to check")
def ebay_sync_sold(days):
    """Sync sold items from eBay — records transactions for cards sold on eBay."""
    from src.api.ebay import EbayClient

    ebay_client = EbayClient()
    session = get_session()
    try:
        orders = ebay_client.get_seller_orders(days=days)
        synced = 0

        for order in orders:
            for item in order.get("lineItems", []):
                sku = item.get("sku", "")
                if not sku.startswith("card-"):
                    continue

                card_id = int(sku.replace("card-", ""))
                card = session.query(Card).filter_by(id=card_id).first()
                if not card or card.status == CardStatus.SOLD:
                    continue

                sale_price = float(item.get("total", {}).get("value", 0))
                if sale_price <= 0:
                    continue

                fees = round(sale_price * 0.1625, 2)
                order_id = order.get("orderId", "")

                # Check if transaction already exists
                existing = (
                    session.query(Transaction)
                    .filter_by(card_id=card_id, transaction_type=TransactionType.SELL)
                    .first()
                )
                if existing:
                    continue

                txn = Transaction(
                    card_id=card_id,
                    transaction_type=TransactionType.SELL,
                    price=sale_price,
                    fees=fees,
                    platform="ebay",
                    ebay_order_id=order_id,
                    notes=f"Synced from eBay order {order_id}",
                )
                session.add(txn)
                card.status = CardStatus.SOLD
                synced += 1

                net = sale_price - fees
                profit = net - (card.purchase_price or 0)
                profit_color = "green" if profit >= 0 else "red"
                console.print(
                    f"  [green]Synced:[/] {card.player[:30]} — "
                    f"sold ${sale_price:,.2f}, net ${net:,.2f}, "
                    f"[{profit_color}]profit ${profit:,.2f}[/]"
                )

        session.commit()
        console.print(f"\n[green]{synced} sales synced from eBay.[/]")
    finally:
        session.close()


if __name__ == "__main__":
    cli()
