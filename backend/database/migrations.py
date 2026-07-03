from database.db import Base, engine
import models  # noqa: F401  (регистрирует все модели в Base.metadata)


def ensure_schema():
    Base.metadata.create_all(bind=engine)
