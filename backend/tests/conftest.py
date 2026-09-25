import os
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("APP_SECRET_KEY", "test-only-secret-" + "x" * 40)
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from app.db import Base, get_db
from app.models import User, Subscription, CollectionJob
from app.auth import hasher
from app.schemas import SubscriptionInput
from app.jobs import subscription_snapshot
from app.db import now


class MemoryCache:
    def __init__(self):
        self.data = {}
    def get(self, key):
        return self.data.get(key)
    def setex(self, key, ttl, value):
        self.data[key] = value
    def set(self, key, value, **kwargs):
        return True
    def incr(self, key):
        self.data[key] = self.data.get(key, 0) + 1
        return self.data[key]
    def expire(self, *args):
        return True
    def delete(self, key):
        self.data.pop(key, None)
    def ping(self):
        return True


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    engine.dispose()


@pytest.fixture
def user(db):
    user = User(email="researcher@example.com", password_hash=hasher.hash("test-password-123"), is_admin=True)
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def sub(db, user):
    sub = Subscription(user_id=user.id, **SubscriptionInput(topic="EEG brain age", keywords=["EEG", "brain age"]).model_dump())
    db.add(sub)
    db.commit()
    return sub


@pytest.fixture
def job(db, sub):
    job = CollectionJob(subscription_id=sub.id, scheduled_for=now(), snapshot=subscription_snapshot(sub))
    db.add(job)
    db.commit()
    return job


@pytest.fixture
def client(db, monkeypatch):
    from app.main import app
    from app import main
    monkeypatch.setattr("redis.Redis.from_url", lambda *a, **k: MemoryCache())
    app.dependency_overrides[get_db] = lambda: db
    class Context:
        def __enter__(self):
            return db
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(main, "SessionLocal", Context)
    with TestClient(app, headers={"Origin": "http://localhost:3000", "X-Requested-With": "S-PAPER"}) as client:
        yield client
    app.dependency_overrides.clear()
