"""added cloumns to data_block

Revision ID: 7e23fdd7ee66
Revises: 929b8d9cd034
Create Date: 2019-10-31 06:55:27.879048

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7e23fdd7ee66'
down_revision = '929b8d9cd034'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('data_block',
                  sa.Column('account_index', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('data_block', 'account_index')

