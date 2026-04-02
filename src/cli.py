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
@click.option("--status", type=click.Choice(["all", "in_collection", "listed", "sold"]), default="all")
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
@click.option("--sport", default="basketball", help="Sport")
@click.option("--price", type=float, help="Purchase price")
@click.option("--graded", is_flag=True, help="Is the card graded?")
@click.option("--grade", type=float, help="Numeric grade (e.g. 10)")
@click.option("--cert", help="PSA/BGS cert number")
@click.option("--source", help="Where you bought it")
def inventory_add(player, year, brand, set_name, sport, price, graded, grade, cert, source):
    """Manually add a card to your inventory."""
    session = get_session()
    try:
        card = Card(
            player=player,
            year=year,
            brand=brand,
            set_name=set_name,
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

        in_collection = [c for c in cards if c.status == CardStatus.IN_COLLECTION]
        sold = [c for c in cards if c.status == CardStatus.SOLD]

        total_invested = sum(c.purchase_price or 0 for c in in_collection)
        total_fmv = sum(c.current_fmv or c.purchase_price or 0 for c in in_collection)

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
        console.print(f"  Total invested:      ${total_invested:,.2f}")
        console.print(f"  Current FMV:         ${total_fmv:,.2f}")
        console.print(f"  Unrealized P&L:      ${unrealized_pnl:,.2f}")
        console.print(f"  Realized P&L:        ${realized_pnl:,.2f}")
        console.print(f"  Total bought:        ${total_bought:,.2f}")
        console.print(f"  Total sold:          ${total_sold:,.2f}")
        console.print(f"  Total fees:          ${total_fees:,.2f}")
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
    """Import purchase history from eBay."""
    from src.importer.ebay_import import import_ebay_purchases
    result = import_ebay_purchases(days=days)
    console.print(f"[green]Imported:[/] {result['imported']} cards")
    console.print(f"[yellow]Skipped:[/] {result['skipped']} (duplicates)")
    if result["errors"]:
        console.print(f"[red]Errors:[/]")
        for err in result["errors"]:
            console.print(f"  - {err}")


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


# ── Grade ──────────────────────────────────────────────────────────

@cli.command()
@click.argument("image_path", type=click.Path(exists=True))
def grade(image_path):
    """Assess a card's likely PSA/BGS grade from an image."""
    from src.engine.grader import assess_grade

    console.print(f"[dim]Analyzing card image: {image_path}[/]")
    result = assess_grade(image_path)

    if result is None:
        console.print("[red]No Anthropic API key configured. Set ANTHROPIC_API_KEY in .env[/]")
        return

    if "error" in result:
        console.print(f"[red]Error: {result['error']}[/]")
        return

    # Card identification
    card = result.get("card", {})
    if card:
        console.print("\n[bold]Card Identified[/]")
        if card.get("player"):
            console.print(f"  Player:    {card['player']}")
        if card.get("year"):
            console.print(f"  Year:      {card['year']}")
        if card.get("brand"):
            console.print(f"  Brand:     {card['brand']}")
        if card.get("set_name"):
            console.print(f"  Set:       {card['set_name']}")
        if card.get("variation"):
            console.print(f"  Variation: {card['variation']}")
        if card.get("serial"):
            console.print(f"  Serial:    {card['serial']}")

    # Sub-grades table
    subs = result.get("sub_grades", {})
    if subs:
        console.print()
        table = Table(title="Sub-Grade Assessment")
        table.add_column("Category", style="cyan")
        table.add_column("Score", justify="right")
        table.add_column("Rating")

        for category in ["centering", "corners", "edges", "surface"]:
            score = subs.get(category)
            if score is not None:
                if score >= 9:
                    rating = "[green]Excellent[/]"
                elif score >= 7:
                    rating = "[yellow]Good[/]"
                elif score >= 5:
                    rating = "[red]Fair[/]"
                else:
                    rating = "[red bold]Poor[/]"
                table.add_row(category.capitalize(), f"{score:.1f}", rating)

        console.print(table)

    # Grade estimates
    console.print()
    if result.get("psa_estimate"):
        psa = result["psa_estimate"]
        label = result.get("psa_label", "")
        console.print(f"  [bold green]PSA Estimate:[/] {psa:.0f} — {label}")
    if result.get("bgs_estimate"):
        bgs = result["bgs_estimate"]
        label = result.get("bgs_label", "")
        console.print(f"  [bold blue]BGS Estimate:[/] {bgs:.1f} — {label}")

    if result.get("notes"):
        console.print(f"\n  [dim]Notes: {result['notes']}[/]")

    console.print()


# ── Goldin Auction — SELLER DEFENSE MODE ──────────────────────────

@cli.group()
def goldin():
    """Defend your Goldin auction lots from low bids."""
    pass


@goldin.command("defend")
@click.option("--tier", type=click.Choice(["A", "B", "C", "D", "all"]), default="all", help="Filter by tier")
@click.option("--player", default=None, help="Filter by player name")
@click.option("--sort", "sort_by", type=click.Choice(["lot", "bid", "gap", "fmv", "danger"]), default="danger", help="Sort by")
def goldin_defend(tier, player, sort_by):
    """Show defense status for all lots — which need protection tonight."""
    from Inventory.goldin_auction_2026_04 import LOTS
    from src.engine.goldin_tracker import analyze_all

    lots = LOTS
    if tier != "all":
        lots = [l for l in lots if l["tier"] == tier]
    if player:
        name = player.lower()
        lots = [l for l in lots if name in l["player"].lower()]

    results = analyze_all(lots)

    sort_keys = {
        "lot": lambda r: r["lot"],
        "bid": lambda r: -r["current_bid"],
        "gap": lambda r: r["floor_gap_pct"],
        "fmv": lambda r: -r["fmv"],
        "danger": lambda r: (
            {"DANGER": 0, "DEFEND": 1, "CLOSE": 2, "SAFE": 3}[r["verdict"]],
            r["floor_gap_pct"],
        ),
    }
    results.sort(key=sort_keys[sort_by])

    table = Table(title=f"SELLER DEFENSE — {len(results)} Lots (you get 115% of hammer)")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Card", style="cyan", max_width=40)
    table.add_column("T", justify="center")
    table.add_column("Bid", justify="right")
    table.add_column("You Net", justify="right")
    table.add_column("eBay Net", justify="right")
    table.add_column("Floor", justify="right")
    table.add_column("vs Floor", justify="right")
    table.add_column("Trend", justify="center")
    table.add_column("Status", style="bold")

    for r in results:
        trend_arrow = {"up": "[green]^[/]", "stable": "[yellow]-[/]", "down": "[red]v[/]"}.get(r["trend"], "?")
        verdict_color = {
            "DANGER": "red bold reverse",
            "DEFEND": "red bold",
            "CLOSE": "yellow bold",
            "SAFE": "green",
        }.get(r["verdict"], "white")
        net_color = "green" if r["vs_ebay"] >= 0 else "red"
        gap_color = "green" if r["floor_gap"] >= 0 else "red"

        table.add_row(
            str(r["lot"]),
            r["card"][:40],
            r["tier"],
            f"${r['current_bid']:,}",
            f"[{net_color}]${r['goldin_net']:,.0f}[/]",
            f"${r['ebay_net']:,.0f}",
            f"${r['floor']:,.0f}",
            f"[{gap_color}]{r['floor_gap_pct']:+.0f}%[/]",
            trend_arrow,
            f"[{verdict_color}]{r['verdict']}[/]",
        )

    console.print(table)

    # Summary counts
    danger = [r for r in results if r["verdict"] == "DANGER"]
    defend = [r for r in results if r["verdict"] == "DEFEND"]
    close = [r for r in results if r["verdict"] == "CLOSE"]
    safe = [r for r in results if r["verdict"] == "SAFE"]

    console.print()
    if danger:
        total_lost = sum(r["vs_ebay"] for r in danger)
        console.print(f"[red bold reverse] DANGER [/] {len(danger)} lots way below floor — losing ${abs(total_lost):,.0f} vs eBay")
    if defend:
        console.print(f"[red bold] DEFEND [/] {len(defend)} lots below floor — bid these up")
    if close:
        console.print(f"[yellow bold] CLOSE  [/] {len(close)} lots near floor — keep watching")
    if safe:
        console.print(f"[green] SAFE   [/] {len(safe)} lots above floor — let them ride")

    console.print(f"\n[dim]Floor = min hammer where Goldin payout (115%) >= eBay net (FMV x 83.75%)[/]")
    console.print(f"[dim]DANGER = >15% below floor | DEFEND = below floor | CLOSE = above but tight | SAFE = 15%+ above[/]")


@goldin.command("lot")
@click.argument("lot_number", type=int)
def goldin_lot(lot_number):
    """Show detailed defense analysis for a single lot."""
    from Inventory.goldin_auction_2026_04 import LOTS
    from src.engine.goldin_tracker import analyze_lot, defense_floor

    lot = None
    for l in LOTS:
        if l["lot"] == lot_number:
            lot = l
            break

    if not lot:
        console.print(f"[red]Lot #{lot_number} not found.[/]")
        return

    r = analyze_lot(lot)
    verdict_color = {"DANGER": "red bold", "DEFEND": "red", "CLOSE": "yellow", "SAFE": "green"}.get(r["verdict"], "white")
    trend_word = {"up": "Trending Up", "stable": "Stable", "down": "Trending Down"}.get(r["trend"], "Unknown")

    console.print(f"\n[bold]Lot #{r['lot']}:[/] {r['card']}")
    console.print(f"  Player:       {r['player']}")
    console.print(f"  Tier:         {r['tier']}")
    console.print(f"  Grade:        {lot.get('grade') or 'Raw'}")
    console.print(f"  Population:   {r['pop'] or 'N/A'}{'  [yellow bold]SCARCE[/]' if r['scarce'] else ''}")
    console.print()

    console.print(f"  [bold]Current Bid:  ${r['current_bid']:,}[/]")
    console.print(f"  You Get (115%):  ${r['goldin_net']:,.0f}")
    console.print(f"  eBay Alt Net:   ${r['ebay_net']:,.0f}  (FMV ${r['fmv']:,} - 16.25% fees)")
    console.print(f"  Confidence:     {r['confidence']}%")
    console.print(f"  Trend:          {trend_word}")
    console.print()

    # Defense floor
    floor = r["floor"]
    gap_color = "green" if r["floor_gap"] >= 0 else "red"
    console.print(f"  [bold]Defense Floor:   ${floor:,.0f}[/]  (min hammer to beat eBay)")
    console.print(f"  Current vs Floor: [{gap_color}]{r['floor_gap_pct']:+.1f}% (${r['floor_gap']:+,.0f})[/]")
    console.print()

    vs_color = "green" if r["vs_ebay"] >= 0 else "red"
    console.print(f"  Goldin vs eBay:  [{vs_color}]${r['vs_ebay']:+,.0f}[/]")
    console.print(f"  Status:          [{verdict_color}]{r['verdict']}[/]")
    console.print()

    if r["verdict"] in ("DANGER", "DEFEND"):
        needed = r["floor"] - r["current_bid"]
        console.print(f"  [red bold]>>> NEEDS ${needed:,.0f} MORE to reach floor <<<[/]")
    elif r["verdict"] == "CLOSE":
        console.print(f"  [yellow]Above floor but thin — watch for late snipers[/]")
    else:
        console.print(f"  [green]Healthy — let it ride[/]")

    console.print()


@goldin.command("update")
@click.argument("lot_number", type=int)
@click.argument("new_bid", type=float)
def goldin_update(lot_number, new_bid):
    """Update a lot's current bid and show new defense status."""
    from Inventory.goldin_auction_2026_04 import LOTS, update_bid
    from src.engine.goldin_tracker import analyze_lot

    lot = None
    for l in LOTS:
        if l["lot"] == lot_number:
            lot = l
            break

    if not lot:
        console.print(f"[red]Lot #{lot_number} not found.[/]")
        return

    old_bid = lot["current_bid"]
    update_bid(lot_number, new_bid)

    change = new_bid - old_bid
    change_pct = (change / old_bid * 100) if old_bid > 0 else 0
    direction = "[green]^[/]" if change > 0 else "[red]v[/]" if change < 0 else "-"

    r = analyze_lot(lot)
    verdict_color = {"DANGER": "red bold", "DEFEND": "red", "CLOSE": "yellow", "SAFE": "green"}.get(r["verdict"], "white")
    net_color = "green" if r["vs_ebay"] >= 0 else "red"

    console.print(f"[bold]Lot #{lot_number}:[/] {lot['card']}")
    console.print(f"  Bid: ${old_bid:,.0f} -> ${new_bid:,.0f}  ({direction} ${abs(change):,.0f}, {change_pct:+.1f}%)")
    console.print(f"  You Net: ${r['goldin_net']:,.0f} | Floor: ${r['floor']:,.0f} | "
                  f"vs eBay: [{net_color}]${r['vs_ebay']:+,.0f}[/] | "
                  f"[{verdict_color}]{r['verdict']}[/]")

    if r["verdict"] in ("DANGER", "DEFEND"):
        needed = r["floor"] - r["current_bid"]
        console.print(f"  [red bold]Still needs ${needed:,.0f} more to reach floor[/]")


@goldin.command("floors")
@click.option("--tier", type=click.Choice(["A", "B", "C", "D", "all"]), default="all")
def goldin_floors(tier):
    """Show defense floor price for every lot — your cheat sheet tonight."""
    from Inventory.goldin_auction_2026_04 import LOTS
    from src.engine.goldin_tracker import analyze_all

    lots = LOTS if tier == "all" else [l for l in LOTS if l["tier"] == tier]
    results = analyze_all(lots)

    table = Table(title=f"DEFENSE FLOORS — Don't let these sell below floor")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Card", style="cyan", max_width=40)
    table.add_column("T", justify="center")
    table.add_column("FMV", justify="right")
    table.add_column("Floor", justify="right", style="bold")
    table.add_column("Bid Now", justify="right")
    table.add_column("Gap", justify="right")
    table.add_column("Status", style="bold")

    for r in results:
        verdict_color = {
            "DANGER": "red bold reverse",
            "DEFEND": "red bold",
            "CLOSE": "yellow bold",
            "SAFE": "green",
        }.get(r["verdict"], "white")
        gap_color = "green" if r["floor_gap"] >= 0 else "red"

        table.add_row(
            str(r["lot"]),
            r["card"][:40],
            r["tier"],
            f"${r['fmv']:,}",
            f"${r['floor']:,.0f}",
            f"${r['current_bid']:,}",
            f"[{gap_color}]${r['floor_gap']:+,.0f}[/]",
            f"[{verdict_color}]{r['verdict']}[/]",
        )

    console.print(table)
    console.print(f"\n[dim]Floor = FMV x 0.8375 / 1.15 = min hammer to match eBay net proceeds[/]")


@goldin.command("refresh")
def goldin_refresh():
    """Fetch live bids from Goldin and update all lots with URLs configured."""
    from Inventory.goldin_auction_2026_04 import LOTS, LOT_URLS
    from src.engine.goldin_tracker import refresh_live_bids

    if not LOT_URLS:
        console.print("[yellow]No Goldin URLs configured.[/]")
        console.print("Add URLs to Inventory/goldin_auction_2026_04.py LOT_URLS dict:")
        console.print('  LOT_URLS = {1: "/item/shaq-nt-...", 2: "/item/curry-topps-..."}')
        console.print("\nOr update bids manually: cardagent goldin update <lot#> <new_bid>")
        return

    console.print(f"[dim]Fetching live bids for {len(LOT_URLS)} lots...[/]")
    changes = refresh_live_bids(LOTS, LOT_URLS)

    if not changes:
        console.print("[green]All bids unchanged.[/]")
        return

    table = Table(title=f"Bid Updates — {len(changes)} changes")
    table.add_column("Lot", justify="right")
    table.add_column("Card", style="cyan")
    table.add_column("Old Bid", justify="right")
    table.add_column("New Bid", justify="right")
    table.add_column("Change", justify="right")

    for c in changes:
        direction = "[green]^[/]" if c["change"] > 0 else "[red]v[/]"
        table.add_row(
            str(c["lot"]),
            c["card"][:40],
            f"${c['old_bid']:,}",
            f"${c['new_bid']:,}",
            f"{direction} ${abs(c['change']):,.0f} ({c['change_pct']:+.1f}%)",
        )

    console.print(table)


if __name__ == "__main__":
    cli()
