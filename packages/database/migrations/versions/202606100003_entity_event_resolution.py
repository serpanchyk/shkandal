"""Prepare entity and event resolution persistence."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202606100003"
down_revision: str | None = "202606100002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""

    op.drop_column("article_entities", "mention_text")
    op.drop_column("article_events", "evidence_text")

    op.add_column("events", sa.Column("event_year", sa.Integer(), nullable=True))
    op.add_column("events", sa.Column("event_month", sa.Integer(), nullable=True))
    op.add_column("events", sa.Column("event_day", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE events
        SET event_year = EXTRACT(YEAR FROM event_date)::integer,
            event_month = CASE WHEN event_date_precision IN ('month', 'day')
                THEN EXTRACT(MONTH FROM event_date)::integer END,
            event_day = CASE WHEN event_date_precision = 'day'
                THEN EXTRACT(DAY FROM event_date)::integer END,
            event_date_precision = CASE
                WHEN event_date_precision IS NOT NULL THEN event_date_precision
                WHEN event_date IS NOT NULL THEN 'day'
                ELSE 'unknown'
            END
        """
    )
    op.alter_column(
        "events",
        "event_date_precision",
        existing_type=sa.Text(),
        nullable=False,
        server_default="unknown",
    )
    op.drop_index("ix_events_event_date", table_name="events")
    op.drop_column("events", "event_date")
    op.create_check_constraint(
        "ck_events_date_parts_precision",
        "events",
        "(event_date_precision = 'unknown' AND event_year IS NULL "
        "AND event_month IS NULL AND event_day IS NULL) OR "
        "(event_date_precision = 'year' AND event_year IS NOT NULL "
        "AND event_month IS NULL AND event_day IS NULL) OR "
        "(event_date_precision = 'month' AND event_year IS NOT NULL "
        "AND event_month IS NOT NULL AND event_day IS NULL) OR "
        "(event_date_precision = 'day' AND event_year IS NOT NULL "
        "AND event_month IS NOT NULL AND event_day IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_events_date_parts_range",
        "events",
        "(event_month IS NULL OR event_month BETWEEN 1 AND 12) AND "
        "(event_day IS NULL OR event_day BETWEEN 1 AND 31)",
    )
    op.create_index(
        "ix_events_event_date_parts",
        "events",
        ["event_year", "event_month", "event_day"],
    )

    op.add_column("case_events", sa.Column("event_year", sa.Integer(), nullable=True))
    op.add_column("case_events", sa.Column("event_month", sa.Integer(), nullable=True))
    op.add_column("case_events", sa.Column("event_day", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE case_events AS case_event
        SET event_year = event.event_year,
            event_month = event.event_month,
            event_day = event.event_day
        FROM events AS event
        WHERE event.id = case_event.event_id
        """
    )
    op.drop_index("ix_case_events_case_id_event_date", table_name="case_events")
    op.drop_column("case_events", "event_date")
    op.create_index(
        "ix_case_events_case_id_event_date_parts",
        "case_events",
        ["case_id", "event_year", "event_month", "event_day"],
    )


def downgrade() -> None:
    """Revert the migration."""

    raise NotImplementedError("entity/event resolution migration is intentionally irreversible")
