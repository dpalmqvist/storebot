"""Advanced analytics module for strategic financial insights.

Aggregates existing data from products, orders, and listings to produce
business summaries, profitability reports, inventory analysis, period
comparisons, and sourcing analysis.
"""

import logging
import re
from datetime import datetime

from sqlalchemy.orm import Session

from storebot.db import Order, PlatformListing, Product
from storebot.tools.helpers import log_action, naive_now

logger = logging.getLogger(__name__)

# Aging bucket boundaries (upper bound in days, inclusive)
_AGING_BUCKETS = [
    ("0-7d", 7),
    ("8-14d", 14),
    ("15-30d", 30),
    ("30+d", None),
]


def _parse_period(period: str | None) -> tuple[datetime, datetime]:
    """Parse a period string into (start, end) naive datetimes.

    Supported formats:
    - None        -> current month
    - "2026-01"   -> January 2026
    - "2026-Q1"   -> Q1 2026 (Jan-Mar)
    - "2026"      -> full year 2026

    Raises ValueError for unrecognised formats.
    """
    if period is None:
        now = naive_now()
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, _next_month(now.year, now.month)

    m = re.fullmatch(r"(\d{4})-(\d{2})", period)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        return datetime(year, month, 1), _next_month(year, month)

    m = re.fullmatch(r"(\d{4})-Q([1-4])", period)
    if m:
        year, quarter = int(m.group(1)), int(m.group(2))
        start_month = (quarter - 1) * 3 + 1
        return datetime(year, start_month, 1), _next_month(year, start_month + 2)

    m = re.fullmatch(r"(\d{4})", period)
    if m:
        year = int(m.group(1))
        return datetime(year, 1, 1), datetime(year + 1, 1, 1)

    raise ValueError(f"Okänt periodformat: {period!r}. Använd YYYY, YYYY-MM eller YYYY-QN.")


def _next_month(year: int, month: int) -> datetime:
    """Return the first day of the month after (year, month)."""
    if month == 12:
        return datetime(year + 1, 1, 1)
    return datetime(year, month + 1, 1)


def _product_profit(product: Product, order: Order) -> float:
    """Calculate net profit for a sold product."""
    return (
        (order.sale_price or 0)
        - (product.acquisition_cost or 0)
        - (order.platform_fee or 0)
        - (order.shipping_cost or 0)
    )


def _time_to_sale_days(session: Session, order: Order) -> int | None:
    """Return days between listing and sale, or None if unavailable."""
    listing = (
        session.query(PlatformListing)
        .filter(
            PlatformListing.product_id == order.product_id,
            PlatformListing.listed_at.isnot(None),
        )
        .first()
    )
    if not listing or not listing.listed_at or not order.ordered_at:
        return None
    days = (order.ordered_at - listing.listed_at).days
    return days if days >= 0 else None


def _avg_or_none(values: list[float]) -> float | None:
    """Return the rounded average of a list, or None if empty."""
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def _accumulate_group(groups: dict[str, dict], key: str, revenue: float, profit: float) -> None:
    """Accumulate revenue and profit into a named group (category or source)."""
    entry = groups.setdefault(key, {"count": 0, "revenue": 0.0, "profit": 0.0})
    entry["count"] += 1
    entry["revenue"] += revenue
    entry["profit"] += profit


def _round_groups(groups: dict[str, dict]) -> None:
    """Round revenue and profit in each group to 2 decimal places."""
    for entry in groups.values():
        entry["revenue"] = round(entry["revenue"], 2)
        entry["profit"] = round(entry["profit"], 2)


def _aging_bucket(days: int) -> str:
    """Return the aging bucket label for a given number of days."""
    for label, upper in _AGING_BUCKETS:
        if upper is None or days <= upper:
            return label
    return "30+d"


class AnalyticsService:
    """Strategic financial analytics over existing database data."""

    def __init__(self, engine):
        self.engine = engine

    def business_summary(self, period: str | None = None) -> dict:
        """KPIs for a period: revenue, costs, profit, margin, items sold, stock, avg time-to-sale."""
        start, end = _parse_period(period)

        with Session(self.engine) as session:
            orders = (
                session.query(Order)
                .filter(Order.ordered_at >= start, Order.ordered_at < end)
                .all()
            )

            total_revenue = 0.0
            total_cost = 0.0
            total_fees = 0.0
            total_shipping = 0.0
            sale_times: list[float] = []

            for order in orders:
                total_revenue += order.sale_price or 0
                total_fees += order.platform_fee or 0
                total_shipping += order.shipping_cost or 0
                if order.product:
                    total_cost += order.product.acquisition_cost or 0
                    days = _time_to_sale_days(session, order)
                    if days is not None:
                        sale_times.append(days)

            gross_profit = total_revenue - total_cost - total_fees - total_shipping
            margin = (gross_profit / total_revenue * 100) if total_revenue > 0 else 0.0

            stock_count = (
                session.query(Product).filter(Product.status.in_(["draft", "listed"])).count()
            )

            log_action(
                session,
                "analytics",
                "business_summary",
                {"period": period, "orders": len(orders)},
            )
            session.commit()

            return {
                "period": period or "current_month",
                "period_start": start.isoformat(),
                "period_end": end.isoformat(),
                "revenue": round(total_revenue, 2),
                "acquisition_cost": round(total_cost, 2),
                "platform_fees": round(total_fees, 2),
                "shipping_cost": round(total_shipping, 2),
                "gross_profit": round(gross_profit, 2),
                "margin_percent": round(margin, 1),
                "items_sold": len(orders),
                "stock_count": stock_count,
                "avg_time_to_sale_days": _avg_or_none(sale_times),
            }

    def profitability_report(self, period: str | None = None) -> dict:
        """Net profit per product, aggregated by category and source. Top/bottom 5."""
        start, end = _parse_period(period)

        with Session(self.engine) as session:
            orders = (
                session.query(Order)
                .filter(Order.ordered_at >= start, Order.ordered_at < end)
                .all()
            )

            products_profit: list[dict] = []
            by_category: dict[str, dict] = {}
            by_source: dict[str, dict] = {}

            for order in orders:
                product = order.product
                if not product:
                    continue

                profit = _product_profit(product, order)
                sale_price = order.sale_price or 0
                category = product.category or "Okänd"
                source = product.source or "Okänd"

                products_profit.append(
                    {
                        "product_id": product.id,
                        "title": product.title,
                        "category": category,
                        "source": source,
                        "sale_price": sale_price,
                        "acquisition_cost": product.acquisition_cost or 0,
                        "platform_fee": order.platform_fee or 0,
                        "shipping_cost": order.shipping_cost or 0,
                        "profit": round(profit, 2),
                    }
                )

                _accumulate_group(by_category, category, sale_price, profit)
                _accumulate_group(by_source, source, sale_price, profit)

            _round_groups(by_category)
            _round_groups(by_source)

            sorted_by_profit = sorted(products_profit, key=lambda x: x["profit"], reverse=True)
            top_5 = sorted_by_profit[:5]
            bottom_5 = sorted_by_profit[-5:] if len(sorted_by_profit) > 5 else sorted_by_profit

            log_action(
                session,
                "analytics",
                "profitability_report",
                {"period": period, "products_analyzed": len(products_profit)},
            )
            session.commit()

            return {
                "period": period or "current_month",
                "total_products": len(products_profit),
                "top_5": top_5,
                "bottom_5": bottom_5,
                "by_category": by_category,
                "by_source": by_source,
            }

    def inventory_report(self) -> dict:
        """Current stock value, status distribution, aging buckets, stale items."""
        now = naive_now()

        with Session(self.engine) as session:
            products = session.query(Product).all()

            status_dist: dict[str, int] = {}
            stock_value = 0.0
            aging: dict[str, list[dict]] = {label: [] for label, _ in _AGING_BUCKETS}

            for product in products:
                status = product.status or "draft"
                status_dist[status] = status_dist.get(status, 0) + 1

                if status in ("draft", "listed"):
                    stock_value += product.acquisition_cost or 0

                    days = (
                        (now - product.created_at.replace(tzinfo=None)).days
                        if product.created_at
                        else 0
                    )
                    item = {
                        "product_id": product.id,
                        "title": product.title,
                        "days_in_stock": days,
                        "acquisition_cost": product.acquisition_cost or 0,
                        "status": status,
                    }
                    aging[_aging_bucket(days)].append(item)

            aging_counts = {k: len(v) for k, v in aging.items()}

            stale_items = sorted(aging["30+d"], key=lambda x: x["days_in_stock"], reverse=True)[
                :10
            ]

            log_action(
                session,
                "analytics",
                "inventory_report",
                {"total_products": len(products), "stock_value": round(stock_value, 2)},
            )
            session.commit()

            return {
                "total_products": len(products),
                "status_distribution": status_dist,
                "stock_value": round(stock_value, 2),
                "aging_counts": aging_counts,
                "stale_items": stale_items,
            }

    def period_comparison(self, period_a: str | None = None, period_b: str | None = None) -> dict:
        """Two periods side-by-side with deltas. Default: current month vs previous month."""
        if period_a is None:
            now = naive_now()
            period_a = f"{now.year}-{now.month:02d}"
        if period_b is None:
            start_a, _ = _parse_period(period_a)
            if start_a.month == 1:
                period_b = f"{start_a.year - 1}-12"
            else:
                period_b = f"{start_a.year}-{start_a.month - 1:02d}"

        summary_a = self.business_summary(period_a)
        summary_b = self.business_summary(period_b)

        deltas = {}
        for key in ("revenue", "gross_profit", "items_sold", "margin_percent"):
            val_a = summary_a.get(key, 0) or 0
            val_b = summary_b.get(key, 0) or 0
            diff = val_a - val_b
            pct = round(diff / val_b * 100, 1) if val_b != 0 else None
            deltas[key] = {"diff": round(diff, 2), "percent_change": pct}

        with Session(self.engine) as session:
            log_action(
                session,
                "analytics",
                "period_comparison",
                {"period_a": period_a, "period_b": period_b},
            )
            session.commit()

        return {
            "period_a": summary_a,
            "period_b": summary_b,
            "deltas": deltas,
        }

    def sourcing_analysis(self, period: str | None = None) -> dict:
        """ROI by source channel: items sourced/sold, margin, avg time-to-sale."""
        start, end = _parse_period(period)

        with Session(self.engine) as session:
            orders = (
                session.query(Order)
                .filter(Order.ordered_at >= start, Order.ordered_at < end)
                .all()
            )

            channels: dict[str, dict] = {}

            for order in orders:
                product = order.product
                if not product:
                    continue

                source = product.source or "Okänd"
                ch = channels.setdefault(
                    source,
                    {
                        "items_sold": 0,
                        "total_revenue": 0.0,
                        "total_cost": 0.0,
                        "total_profit": 0.0,
                        "sale_times": [],
                    },
                )
                ch["items_sold"] += 1
                ch["total_revenue"] += order.sale_price or 0
                ch["total_cost"] += product.acquisition_cost or 0
                ch["total_profit"] += _product_profit(product, order)

                days = _time_to_sale_days(session, order)
                if days is not None:
                    ch["sale_times"].append(days)

            # Count sourced items per channel
            sourced_products = (
                session.query(Product)
                .filter(Product.created_at >= start, Product.created_at < end)
                .all()
            )
            sourced_by_channel: dict[str, int] = {}
            for p in sourced_products:
                src = p.source or "Okänd"
                sourced_by_channel[src] = sourced_by_channel.get(src, 0) + 1

            # Build result, merging sales data with sourcing counts
            result_channels: dict[str, dict] = {}
            for source in set(channels) | set(sourced_by_channel):
                ch = channels.get(source, {})
                cost = ch.get("total_cost", 0)
                profit = ch.get("total_profit", 0)
                result_channels[source] = {
                    "items_sourced": sourced_by_channel.get(source, 0),
                    "items_sold": ch.get("items_sold", 0),
                    "total_revenue": round(ch.get("total_revenue", 0), 2),
                    "total_cost": round(cost, 2),
                    "total_profit": round(profit, 2),
                    "roi_percent": round(profit / cost * 100, 1) if cost > 0 else None,
                    "avg_time_to_sale": _avg_or_none(ch.get("sale_times", [])),
                }

            with_sales = {k: v for k, v in result_channels.items() if v["items_sold"] > 0}
            best = (
                max(with_sales, key=lambda k: with_sales[k]["total_profit"])
                if with_sales
                else None
            )
            worst = (
                min(with_sales, key=lambda k: with_sales[k]["total_profit"])
                if with_sales
                else None
            )

            log_action(
                session,
                "analytics",
                "sourcing_analysis",
                {"period": period, "channels": len(result_channels)},
            )
            session.commit()

            return {
                "period": period or "current_month",
                "channels": result_channels,
                "best_channel": best,
                "worst_channel": worst,
            }

    # --- Swedish text formatters ---

    @staticmethod
    def _format_summary(data: dict) -> str:
        lines = [
            "Affärssammanfattning\n",
            f"Period: {data.get('period', '-')}",
            f"Intäkter: {data['revenue']:.0f} kr",
            f"Inköpskostnad: {data['acquisition_cost']:.0f} kr",
            f"Plattformsavgifter: {data['platform_fees']:.0f} kr",
            f"Fraktkostnad: {data['shipping_cost']:.0f} kr",
            f"Bruttovinst: {data['gross_profit']:.0f} kr",
            f"Marginal: {data['margin_percent']:.1f}%",
            f"Antal sålda: {data['items_sold']}",
            f"Lager: {data['stock_count']} artiklar",
        ]
        if data.get("avg_time_to_sale_days") is not None:
            lines.append(f"Snittid till försäljning: {data['avg_time_to_sale_days']} dagar")
        return "\n".join(lines)

    @staticmethod
    def _format_profitability(data: dict) -> str:
        lines = [
            "Lönsamhetsrapport\n",
            f"Period: {data.get('period', '-')}",
            f"Analyserade produkter: {data['total_products']}",
        ]

        if data["top_5"]:
            lines.append("\nTopp 5:")
            for p in data["top_5"]:
                lines.append(f"  {p['title']}: {p['profit']:.0f} kr vinst")

        if data["bottom_5"] and data["total_products"] > 5:
            lines.append("\nBotten 5:")
            for p in data["bottom_5"]:
                lines.append(f"  {p['title']}: {p['profit']:.0f} kr vinst")

        if data["by_category"]:
            lines.append("\nPer kategori:")
            for cat, d in data["by_category"].items():
                lines.append(f"  {cat}: {d['count']} st, {d['profit']:.0f} kr vinst")

        return "\n".join(lines)

    @staticmethod
    def _format_inventory(data: dict) -> str:
        lines = [
            "Lagerrapport\n",
            f"Totalt: {data['total_products']} produkter",
            f"Lagervärde: {data['stock_value']:.0f} kr",
        ]

        if data["status_distribution"]:
            lines.append("\nStatus:")
            for status, count in data["status_distribution"].items():
                lines.append(f"  {status}: {count}")

        aging = data.get("aging_counts", {})
        if any(v > 0 for v in aging.values()):
            lines.append("\nÅlder i lager:")
            for bucket, count in aging.items():
                lines.append(f"  {bucket}: {count}")

        stale = data.get("stale_items", [])
        if stale:
            lines.append("\nGamla artiklar (30+ dagar):")
            for item in stale:
                lines.append(
                    f"  {item['title']} — {item['days_in_stock']}d, "
                    f"{item['acquisition_cost']:.0f} kr"
                )

        return "\n".join(lines)

    @staticmethod
    def _format_comparison(data: dict) -> str:
        a = data["period_a"]
        b = data["period_b"]
        lines = [
            "Periodjämförelse\n",
            f"Period A: {a.get('period', '-')}",
            f"Period B: {b.get('period', '-')}\n",
        ]

        for key, label in [
            ("revenue", "Intäkter"),
            ("gross_profit", "Bruttovinst"),
            ("items_sold", "Antal sålda"),
            ("margin_percent", "Marginal (%)"),
        ]:
            val_a = a.get(key, 0) or 0
            val_b = b.get(key, 0) or 0
            delta = data["deltas"].get(key, {})
            diff = delta.get("diff", 0)
            pct = delta.get("percent_change")
            sign = "+" if diff >= 0 else ""
            pct_str = f" ({sign}{pct}%)" if pct is not None else ""
            if key == "margin_percent":
                lines.append(f"{label}: {val_a:.1f}% vs {val_b:.1f}% ({sign}{diff:.1f}pp)")
            else:
                fmt_a = f"{val_a:.0f}" if isinstance(val_a, float) else str(val_a)
                fmt_b = f"{val_b:.0f}" if isinstance(val_b, float) else str(val_b)
                lines.append(f"{label}: {fmt_a} vs {fmt_b} ({sign}{diff:.0f}{pct_str})")

        return "\n".join(lines)

    def _format_full_report(self, summary: dict, profitability: dict, inventory: dict) -> str:
        """Combined report for /rapport, fits within 4000 chars."""
        text = "\n".join(
            [
                self._format_summary(summary),
                "",
                self._format_profitability(profitability),
                "",
                self._format_inventory(inventory),
            ]
        )
        if len(text) > 3900:
            text = text[:3900] + "\n\n...avkortat"
        return text
