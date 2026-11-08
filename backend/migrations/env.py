from alembic import context
from app.core.config import Settings
from app.db.session import make_engine
from app.models.entities import Base

settings = Settings()
target_metadata = Base.metadata
url = settings.database_url.get_secret_value()
if context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, dialect_opts={'paramstyle': 'named'})
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = make_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
