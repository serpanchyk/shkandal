"""Create initial Shkandal schema."""

from collections.abc import Sequence

from alembic import op
from shkandal_database.models import Base

revision: str = "202606010001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""

    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    """Revert the migration."""

    Base.metadata.drop_all(bind=op.get_bind())
