"""create data_transfer table

Revision ID: da27ec2d33df
Revises: bd15422cbe5b
Create Date: 2019-09-24 02:04:58.039630

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'da27ec2d33df'
down_revision = 'bd15422cbe5b'
branch_labels = None
depends_on = None


def upgrade():
    
    op.create_table('data_transfer',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('spec_version', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )



def downgrade():
    op.drop_table('data_transfer')
