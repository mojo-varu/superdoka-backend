"""Fix machine_assignments unique constraint

Revision ID: 005_fix_assignment_constraint
Revises: 004_add_machine_alias
Create Date: 2026-04-30

Old constraint: (machine_id, is_active) — wrongly blocked multiple operators
  being assigned to the same machine.
New constraint: (operator_id, machine_id) — prevents the same operator being
  assigned to the same machine twice, while allowing multiple operators per machine.
"""

from alembic import op

revision = "005_fix_assignment_constraint"
down_revision = "004_add_machine_alias"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("unique_active_assignment", "machine_assignments", type_="unique")
    op.create_unique_constraint(
        "uq_assignment_operator_machine",
        "machine_assignments",
        ["operator_id", "machine_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_assignment_operator_machine", "machine_assignments", type_="unique")
    op.create_unique_constraint(
        "unique_active_assignment",
        "machine_assignments",
        ["machine_id", "is_active"],
    )
