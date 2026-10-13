"""Revision ${up_revision}: ${message}.

Revises: ${comma(down_revision) or "nothing, the first revision"}
Create Date: ${create_date}
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: str | Sequence[str] | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Downgrade the schema to the revision before this one."""
    ${downgrades if downgrades else "pass"}
