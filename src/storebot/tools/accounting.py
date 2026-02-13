import logging
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet

from storebot.db import Voucher, VoucherRow

logger = logging.getLogger(__name__)

BAS_ACCOUNTS = {
    1910: "Kassa",
    1930: "Företagskonto",
    2611: "Utgående moms 25%",
    2640: "Ingående moms",
    3001: "Försäljning varor",
    4010: "Inköp varor",
    6250: "Porto/frakt",
    6570: "Bankkostnader",
}


class AccountingService:
    def __init__(self, engine: sa.Engine, export_path: str = "data/vouchers"):
        self.engine = engine
        self.export_path = Path(export_path)

    def _next_voucher_number(self, session: sa.orm.Session) -> str:
        max_id = session.execute(sa.select(sa.func.max(Voucher.id))).scalar()
        return f"V-{(max_id or 0) + 1:03d}"

    def create_voucher(
        self,
        description: str,
        rows: list[dict],
        order_id: int | None = None,
        transaction_date: str | None = None,
    ) -> dict:
        total_debit = sum(r.get("debit", 0) for r in rows)
        total_credit = sum(r.get("credit", 0) for r in rows)
        if abs(total_debit - total_credit) > 0.01:
            return {
                "error": f"Debet ({total_debit:.2f}) och kredit ({total_credit:.2f}) balanserar inte"
            }

        if transaction_date:
            tx_date = datetime.fromisoformat(transaction_date)
        else:
            tx_date = datetime.now(UTC)

        with sa.orm.Session(self.engine) as session:
            voucher_number = self._next_voucher_number(session)
            voucher = Voucher(
                voucher_number=voucher_number,
                description=description,
                transaction_date=tx_date,
                order_id=order_id,
            )
            session.add(voucher)
            session.flush()

            for row in rows:
                account = row["account"]
                account_name = row.get("account_name") or BAS_ACCOUNTS.get(
                    account, f"Konto {account}"
                )
                voucher_row = VoucherRow(
                    voucher_id=voucher.id,
                    account_number=account,
                    account_name=account_name,
                    debit=row.get("debit", 0),
                    credit=row.get("credit", 0),
                )
                session.add(voucher_row)

            session.commit()

            return {
                "voucher_id": voucher.id,
                "voucher_number": voucher.voucher_number,
                "description": voucher.description,
                "transaction_date": voucher.transaction_date.isoformat(),
                "order_id": voucher.order_id,
                "rows": [
                    {
                        "account": r.account_number,
                        "account_name": r.account_name,
                        "debit": r.debit,
                        "credit": r.credit,
                    }
                    for r in voucher.rows
                ],
            }

    def get_vouchers(self, from_date: str | None = None, to_date: str | None = None) -> list[dict]:
        with sa.orm.Session(self.engine) as session:
            query = sa.select(Voucher).order_by(Voucher.id)

            if from_date:
                query = query.where(Voucher.transaction_date >= datetime.fromisoformat(from_date))
            if to_date:
                query = query.where(Voucher.transaction_date <= datetime.fromisoformat(to_date))

            vouchers = session.scalars(query).all()
            return [
                {
                    "voucher_id": v.id,
                    "voucher_number": v.voucher_number,
                    "description": v.description,
                    "transaction_date": v.transaction_date.isoformat(),
                    "order_id": v.order_id,
                    "rows": [
                        {
                            "account": r.account_number,
                            "account_name": r.account_name,
                            "debit": r.debit,
                            "credit": r.credit,
                        }
                        for r in v.rows
                    ],
                }
                for v in vouchers
            ]

    def _build_voucher_story(self, voucher: Voucher, styles) -> list:
        """Build reportlab story elements for a single voucher."""
        elements = []

        elements.append(
            Paragraph(
                f"Verifikation #{voucher.voucher_number}",
                styles["Title"],
            )
        )
        elements.append(Spacer(1, 4 * mm))
        elements.append(
            Paragraph(
                f"<b>Datum:</b> {voucher.transaction_date.strftime('%Y-%m-%d')}",
                styles["Normal"],
            )
        )
        elements.append(
            Paragraph(
                f"<b>Beskrivning:</b> {voucher.description}",
                styles["Normal"],
            )
        )
        if voucher.order_id:
            elements.append(
                Paragraph(
                    f"<b>Order:</b> #{voucher.order_id}",
                    styles["Normal"],
                )
            )
        elements.append(Spacer(1, 6 * mm))

        table_data = [["Konto", "Kontonamn", "Debet", "Kredit"]]
        total_debit = 0.0
        total_credit = 0.0
        for row in voucher.rows:
            table_data.append(
                [
                    str(row.account_number),
                    row.account_name,
                    f"{row.debit:.2f}" if row.debit else "",
                    f"{row.credit:.2f}" if row.credit else "",
                ]
            )
            total_debit += row.debit
            total_credit += row.credit
        table_data.append(["", "Summa", f"{total_debit:.2f}", f"{total_credit:.2f}"])

        col_widths = [60, 200, 80, 80]
        table = Table(table_data, colWidths=col_widths)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4472C4")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                    ("ALIGN", (2, 0), (3, -1), "RIGHT"),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black),
                ]
            )
        )
        elements.append(table)
        return elements

    def export_voucher_pdf(self, voucher_id: int) -> str:
        self.export_path.mkdir(parents=True, exist_ok=True)

        with sa.orm.Session(self.engine) as session:
            voucher = session.get(Voucher, voucher_id)
            if not voucher:
                raise ValueError(f"Verifikation {voucher_id} hittades inte")

            # Eagerly load rows
            _ = voucher.rows

            filename = f"{voucher.voucher_number}.pdf"
            filepath = self.export_path / filename

            doc = SimpleDocTemplate(str(filepath), pagesize=A4)
            styles = getSampleStyleSheet()
            story = self._build_voucher_story(voucher, styles)
            doc.build(story)

            logger.info("Exported voucher PDF: %s", filepath)
            return str(filepath)

    def export_vouchers_pdf(self, from_date: str, to_date: str) -> dict:
        self.export_path.mkdir(parents=True, exist_ok=True)

        from_dt = datetime.fromisoformat(from_date)
        to_dt = datetime.fromisoformat(to_date)

        with sa.orm.Session(self.engine) as session:
            vouchers = session.scalars(
                sa.select(Voucher)
                .where(Voucher.transaction_date >= from_dt)
                .where(Voucher.transaction_date <= to_dt)
                .order_by(Voucher.id)
            ).all()

            if not vouchers:
                raise ValueError(f"Inga verifikationer hittades mellan {from_date} och {to_date}")

            # Eagerly load rows
            for v in vouchers:
                _ = v.rows

            filename = f"verifikationer_{from_date}_{to_date}.pdf"
            filepath = self.export_path / filename

            doc = SimpleDocTemplate(str(filepath), pagesize=A4)
            styles = getSampleStyleSheet()
            story = []

            story.append(
                Paragraph(
                    f"Verifikationer {from_date} — {to_date}",
                    styles["Title"],
                )
            )
            story.append(Spacer(1, 8 * mm))

            for i, voucher in enumerate(vouchers):
                story.extend(self._build_voucher_story(voucher, styles))
                if i < len(vouchers) - 1:
                    story.append(Spacer(1, 12 * mm))

            doc.build(story)

            logger.info("Exported %d vouchers to PDF: %s", len(vouchers), filepath)
            return {"pdf_path": str(filepath)}
