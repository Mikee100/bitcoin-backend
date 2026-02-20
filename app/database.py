from __future__ import annotations

import os
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


# On Render you can set DATABASE_URL (e.g. PostgreSQL); otherwise SQLite is used (ephemeral on free tier).
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./signals.db")
# Render PostgreSQL URLs use "postgres://"; SQLAlchemy 1.4+ expects "postgresql://".
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)


class Base(DeclarativeBase):
    pass


class SignalRecord(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    timeframe: Mapped[str] = mapped_column(String(10), index=True)
    signal: Mapped[str] = mapped_column(String(20), index=True)
    price: Mapped[float] = mapped_column(Float)
    generated_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    reason: Mapped[str] = mapped_column(String(512))


class VirtualAccount(Base):
    __tablename__ = "virtual_account"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    balance: Mapped[float] = mapped_column(Float, default=10000.0)  # Starting with $10,000
    starting_balance: Mapped[float] = mapped_column(Float, default=10000.0)
    position_size_pct: Mapped[float] = mapped_column(Float, default=100.0)  # Position size as percentage of balance (default 100%)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class VirtualPosition(Base):
    __tablename__ = "virtual_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    direction: Mapped[str] = mapped_column(String(10))  # "LONG" or "SHORT"
    entry_price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    entry_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    current_price: Mapped[float] = mapped_column(Float)  # Updated on each signal


class VirtualTrade(Base):
    __tablename__ = "virtual_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    direction: Mapped[str] = mapped_column(String(10))  # "LONG" or "SHORT"
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    entry_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    exit_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    pnl: Mapped[float] = mapped_column(Float)  # Profit/Loss in USD
    pnl_pct: Mapped[float] = mapped_column(Float)  # Profit/Loss percentage
    fees: Mapped[float] = mapped_column(Float, default=0.0)  # Trading fees


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)

