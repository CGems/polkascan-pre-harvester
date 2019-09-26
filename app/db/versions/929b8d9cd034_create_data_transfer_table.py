"""create data_transfer table

Revision ID: 929b8d9cd034
Revises: bd15422cbe5b
Create Date: 2019-09-26 07:32:33.208731

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '929b8d9cd034'
down_revision = 'bd15422cbe5b'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('data_transfer',
                    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
                    sa.Column('block_id', sa.Integer(), nullable=False),
                    sa.Column('extrinsic_idx', sa.Integer(), nullable=False),
                    sa.Column('data_extrinsic_idx', sa.String(255), nullable=False),
                    sa.Column('transfer_from', sa.String(255), nullable=True),
                    sa.Column('from_raw', sa.String(255), nullable=True),
                    sa.Column('transfer_to', sa.String(255), nullable=True),
                    sa.Column('to_raw', sa.String(255), nullable=True),
                    sa.Column('hash', sa.String(255), nullable=True),
                    sa.Column('amount', sa.DECIMAL(precision=32, scale=16), nullable=False),
                    sa.Column('block_timestamp', sa.DateTime(timezone=True), nullable=True),
                    sa.Column('module_id', sa.String(64), nullable=False),
                    sa.Column('success', sa.SmallInteger(), nullable=True),
                    sa.Column('error', sa.SmallInteger(), nullable=True),
                    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
                    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
                    sa.PrimaryKeyConstraint('id')
                    )

    op.create_index(op.f('ix_data_transfer_extrinsic_idx'), 'data_transfer', ['extrinsic_idx'], unique=False)
    op.create_index(op.f('ix_data_transfer_block_id'), 'data_transfer', ['block_id'], unique=False)
    op.create_index(op.f('ix_data_transfer_transfer_from'), 'data_transfer', ['transfer_from'], unique=False)
    op.create_index(op.f('ix_data_transfer_transfer_to'), 'data_transfer', ['transfer_to'], unique=False)
    op.create_index(op.f('ix_data_transfer_hash'), 'data_transfer', ['hash'], unique=False)
    op.create_index(op.f('ix_data_transfer_block_timestamp'), 'data_transfer', ['block_timestamp'], unique=False)
    op.create_index(op.f('ix_data_transfer_block_module_id'), 'data_transfer', ['module_id'], unique=False)
    op.create_index(op.f('ix_data_transfer_block_success'), 'data_transfer', ['success'], unique=False)
    op.create_index(op.f('ix_data_transfer_block_error'), 'data_transfer', ['error'], unique=False)


def downgrade():
    op.drop_table('data_transfer')
