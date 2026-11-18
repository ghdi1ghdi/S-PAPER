"""subscription_paper relevance score"""
from alembic import op
import sqlalchemy as sa

revision = 'b7c1e2d4a9f0'
down_revision = '04291efa93ce'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('subscription_papers', sa.Column('relevance', sa.Float(), nullable=True))


def downgrade():
    op.drop_column('subscription_papers', 'relevance')
