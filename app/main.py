from datetime import datetime

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.database import SessionLocal, SignalRecord, VirtualAccount, VirtualPosition, VirtualTrade, init_db
from app.models import (
    BacktestResult,
    BacktestTrade,
    CandlesResponse,
    ChartCandle,
    SignalHistoryResponse,
    SignalType,
    Timeframe,
    TradeSignal,
    UpdatePositionSizeRequest,
    VirtualAccountResponse,
    VirtualPositionResponse,
    VirtualPositionsResponse,
    VirtualTradeResponse,
    VirtualTradesResponse,
)
from app.services.data_provider import fetch_klines
from app.services.notify import send_trade_alert, send_test_email
from app.services.strategy import generate_simple_trend_signal, get_htf_trend
from app.services.virtual_trading import VirtualTradingService

# Only email when we first see an entry (not on every poll). Key (symbol, tf) -> last notified signal.
_last_notified: dict[tuple[str, str], SignalType | None] = {}

app = FastAPI(
    title="BTC Trading Signals API",
    description="Backend service for Bitcoin trade signal generation.",
    version="0.1.0",
)

# Allow the Next.js frontend to call this API from the browser.
# In production (e.g. Render), set CORS_ORIGINS to your frontend URL(s), comma-separated.
_settings = get_settings()
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5000",
    "http://127.0.0.1:5000",
] + _settings.get_cors_origins_list()

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """
    Basic health endpoint so we can quickly see if the backend is running.
    """
    return {"status": "ok"}


@app.get("/api/notify/test")
def test_email():
    """
    Send one test email to your NOTIFY_EMAIL. Use this to verify SMTP settings.
    Returns { "ok": true, "message": "..." } or { "ok": false, "error": "..." }.
    """
    success, message = send_test_email()
    if success:
        return {"ok": True, "message": message}
    return {"ok": False, "error": message}


@app.on_event("startup")
def on_startup() -> None:
    # Ensure database tables exist
    init_db()
    
    # Run SQLite-only migration for position_size_pct column if needed (skip for PostgreSQL)
    from app.database import DATABASE_URL
    if "sqlite" in DATABASE_URL:
        try:
            import sqlite3
            import os
            db_path = "./signals.db"
            if os.path.exists(db_path):
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(virtual_account)")
                columns = [col[1] for col in cursor.fetchall()]
                if "position_size_pct" not in columns:
                    cursor.execute("ALTER TABLE virtual_account ADD COLUMN position_size_pct REAL DEFAULT 100.0")
                    conn.commit()
                cursor.execute("UPDATE virtual_account SET position_size_pct = 100.0 WHERE position_size_pct IS NULL")
                conn.commit()
                conn.close()
        except Exception as e:
            print(f"Migration warning: {e}")


@app.get("/api/signal/latest", response_model=TradeSignal)
async def get_latest_signal(
    background_tasks: BackgroundTasks,
    symbol: str = Query(None, description="Trading pair symbol, e.g. BTCUSDT"),
    timeframe: Timeframe = Query(Timeframe.m15, description="Candle interval"),
):
    """
    Generate a simple EMA-based trend signal for the requested symbol/timeframe.
    This currently uses live candles from Binance's public API.
    """
    settings = get_settings()
    use_symbol = symbol or settings.default_symbol

    candles = await fetch_klines(use_symbol, timeframe=timeframe, limit=250)
    htf_trend = None
    if timeframe == Timeframe.m15:
        try:
            htf_candles = await fetch_klines(use_symbol, timeframe=Timeframe.h1, limit=250)
            htf_trend = get_htf_trend(htf_candles)
        except httpx.HTTPError:
            # If higher timeframe fetch fails, continue without HTF trend
            # This allows the endpoint to still return a signal based on the main timeframe
            pass
    signal = generate_simple_trend_signal(
        use_symbol, timeframe=timeframe, candles=candles, htf_trend=htf_trend
    )

    # Persist a lightweight version of the signal for history
    db = SessionLocal()
    try:
        db_signal = SignalRecord(
            symbol=signal.symbol,
            timeframe=signal.timeframe.value,
            signal=signal.signal.value,
            price=signal.price,
            generated_at=signal.generated_at,
            reason=signal.reason[:500],
        )
        db.add(db_signal)
        db.commit()
    finally:
        db.close()

    # Execute virtual trade based on signal
    db_virtual = SessionLocal()
    try:
        VirtualTradingService.execute_trade(
            db_virtual,
            use_symbol,
            signal.signal,
            signal.price,
            signal.generated_at,
        )
    except Exception as e:
        # Log error but don't fail the signal endpoint
        print(f"Virtual trading error: {e}")
    finally:
        db_virtual.close()

    # Email alert only when a new trade opportunity appears (LONG_ENTRY or SHORT_ENTRY)
    key = (use_symbol, timeframe.value)
    if signal.signal in (SignalType.LONG_ENTRY, SignalType.SHORT_ENTRY):
        if _last_notified.get(key) != signal.signal:
            _last_notified[key] = signal.signal
            background_tasks.add_task(send_trade_alert, signal)
    else:
        _last_notified[key] = None

    return signal


@app.get("/api/candles", response_model=CandlesResponse)
async def get_candles(
    symbol: str = Query("BTCUSDT", description="Trading pair symbol"),
    timeframe: Timeframe = Query(Timeframe.m15, description="Candle interval"),
    limit: int = Query(100, ge=30, le=300, description="Number of candles"),
):
    """Return OHLCV candles for charting. Time is Unix seconds."""
    use_symbol = symbol.upper()
    try:
        raw = await fetch_klines(use_symbol, timeframe=timeframe, limit=limit)
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Unable to fetch market data from Binance: {str(e)}"
        )
    candles = [
        ChartCandle(
            time=int(c.open_time.timestamp()),
            open=c.open,
            high=c.high,
            low=c.low,
            close=c.close,
            volume=c.volume,
        )
        for c in raw
    ]
    return CandlesResponse(symbol=use_symbol, timeframe=timeframe.value, candles=candles)


@app.get("/api/signals/history", response_model=SignalHistoryResponse)
def get_signal_history(
    symbol: str | None = Query(None, description="Filter by symbol, e.g. BTCUSDT"),
    timeframe: Timeframe | None = Query(None, description="Filter by timeframe"),
    limit: int = Query(50, ge=1, le=500, description="Max number of records to return"),
):
    """
    Return the most recent stored signals from the database.
    """
    db = SessionLocal()
    try:
        query = db.query(SignalRecord).order_by(SignalRecord.generated_at.desc())
        if symbol:
            query = query.filter(SignalRecord.symbol == symbol.upper())
        if timeframe:
            query = query.filter(SignalRecord.timeframe == timeframe.value)
        rows = query.limit(limit).all()

        signals: list[TradeSignal] = []
        for row in rows:
            signals.append(
                TradeSignal(
                    symbol=row.symbol,
                    timeframe=Timeframe(row.timeframe),
                    signal=SignalType(row.signal),
                    price=row.price,
                    generated_at=row.generated_at,
                    reason=row.reason,
                    extra=None,
                )
            )

        return SignalHistoryResponse(signals=list(reversed(signals)))
    finally:
        db.close()


@app.get("/api/backtest", response_model=BacktestResult)
async def backtest_strategy(
    symbol: str = Query("BTCUSDT", description="Trading pair symbol"),
    timeframe: Timeframe = Query(Timeframe.m15, description="Candle interval"),
    limit: int = Query(1500, ge=300, le=5000, description="Number of candles to use"),
    fee_bps: int = Query(
        8,
        ge=0,
        le=100,
        description="Approx. round-trip fee in basis points (0.01%). 8 = 0.08%.",
    ),
):
    """
    Naive backtest: apply the current strategy over historical candles
    and simulate entering/exiting on LONG/SHORT signals.
    """
    use_symbol = symbol.upper()
    try:
        candles = await fetch_klines(use_symbol, timeframe=timeframe, limit=limit)
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Unable to fetch market data from Binance: {str(e)}"
        )

    trades: list[BacktestTrade] = []
    position: SignalType | None = None
    entry_price: float | None = None
    entry_time: datetime | None = None
    equity = 1.0  # start with 1 unit of capital
    peak_equity = 1.0
    max_drawdown = 0.0
    fee_rate = fee_bps / 10000.0  # convert bps to fraction, applied per completed trade

    for i in range(250, len(candles)):  # reuse large window for indicators
        window = candles[: i + 1]
        sig = generate_simple_trend_signal(use_symbol, timeframe=timeframe, candles=window)
        last_candle = window[-1]

        # Enter positions
        if position is None:
            if sig.signal == SignalType.LONG_ENTRY:
                position = SignalType.LONG_ENTRY
                entry_price = sig.price
                entry_time = last_candle.open_time
            elif sig.signal == SignalType.SHORT_ENTRY:
                position = SignalType.SHORT_ENTRY
                entry_price = sig.price
                entry_time = last_candle.open_time
            continue

        # Exit positions
        exit_now = False
        if position == SignalType.LONG_ENTRY and sig.signal in {SignalType.LONG_EXIT, SignalType.SHORT_ENTRY}:
            exit_now = True
        elif position == SignalType.SHORT_ENTRY and sig.signal in {SignalType.SHORT_EXIT, SignalType.LONG_ENTRY}:
            exit_now = True

        if exit_now and entry_price is not None and entry_time is not None:
            exit_price = sig.price
            if position == SignalType.LONG_ENTRY:
                gross_ret = (exit_price - entry_price) / entry_price
            else:
                gross_ret = (entry_price - exit_price) / entry_price

            # subtract trading fees (round trip) from return
            net_ret = gross_ret - fee_rate

            equity *= 1.0 + net_ret
            peak_equity = max(peak_equity, equity)
            drawdown = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0
            max_drawdown = max(max_drawdown, drawdown)

            trades.append(
                BacktestTrade(
                    entry_time=entry_time,
                    exit_time=last_candle.open_time,
                    direction=position,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    return_pct=net_ret * 100.0,
                )
            )

            # reset position
            if sig.signal in {SignalType.LONG_ENTRY, SignalType.SHORT_ENTRY}:
                # flip immediately into new position
                position = sig.signal
                entry_price = sig.price
                entry_time = last_candle.open_time
            else:
                position = None
                entry_price = None
                entry_time = None

    num_trades = len(trades)
    if num_trades == 0:
        return BacktestResult(
            symbol=use_symbol,
            timeframe=timeframe,
            trades=[],
            gross_return_pct=0.0,
            net_return_pct=0.0,
            total_fees_pct=0.0,
            max_drawdown_pct=0.0,
            win_rate_pct=0.0,
            long_win_rate_pct=0.0,
            short_win_rate_pct=0.0,
            num_long_trades=0,
            num_short_trades=0,
            num_trades=0,
        )

    net_return_pct = (equity - 1.0) * 100.0
    # Approximate gross by adding back fees per trade
    total_fees = fee_rate * num_trades
    gross_equity = equity / (1.0 - total_fees) if (1.0 - total_fees) > 0 else equity
    gross_return_pct = (gross_equity - 1.0) * 100.0

    wins = sum(1 for t in trades if t.return_pct > 0)
    win_rate_pct = wins / num_trades * 100.0

    long_trades = [t for t in trades if t.direction == SignalType.LONG_ENTRY]
    short_trades = [t for t in trades if t.direction == SignalType.SHORT_ENTRY]
    long_wins = sum(1 for t in long_trades if t.return_pct > 0)
    short_wins = sum(1 for t in short_trades if t.return_pct > 0)

    long_win_rate_pct = (long_wins / len(long_trades) * 100.0) if long_trades else 0.0
    short_win_rate_pct = (short_wins / len(short_trades) * 100.0) if short_trades else 0.0

    return BacktestResult(
        symbol=use_symbol,
        timeframe=timeframe,
        trades=trades,
        gross_return_pct=gross_return_pct,
        net_return_pct=net_return_pct,
        total_fees_pct=total_fees * 100.0,
        max_drawdown_pct=max_drawdown * 100.0,
        win_rate_pct=win_rate_pct,
        long_win_rate_pct=long_win_rate_pct,
        short_win_rate_pct=short_win_rate_pct,
        num_long_trades=len(long_trades),
        num_short_trades=len(short_trades),
        num_trades=num_trades,
    )


@app.get("/api/virtual/account", response_model=VirtualAccountResponse)
def get_virtual_account():
    """Get virtual trading account status and performance metrics."""
    db = SessionLocal()
    try:
        account = VirtualTradingService.get_or_create_account(db)
        metrics = VirtualTradingService.get_performance_metrics(db)
        # Ensure position_size_pct exists (for migration compatibility)
        position_size_pct = getattr(account, 'position_size_pct', 100.0)
        if position_size_pct is None:
            position_size_pct = 100.0
        metrics["position_size_pct"] = position_size_pct
        return VirtualAccountResponse(**metrics)
    except Exception as e:
        # Log the error for debugging
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error fetching virtual account: {str(e)}")
    finally:
        db.close()


@app.put("/api/virtual/account/position-size")
def update_position_size(request: UpdatePositionSizeRequest):
    """Update the position size percentage for virtual trading."""
    if request.position_size_pct < 1.0 or request.position_size_pct > 100.0:
        raise HTTPException(
            status_code=400,
            detail="Position size percentage must be between 1.0 and 100.0"
        )
    
    db = SessionLocal()
    try:
        account = VirtualTradingService.get_or_create_account(db)
        account.position_size_pct = request.position_size_pct
        account.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(account)
        return {
            "message": "Position size updated successfully",
            "position_size_pct": account.position_size_pct
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error updating position size: {str(e)}")
    finally:
        db.close()


@app.get("/api/virtual/trades", response_model=VirtualTradesResponse)
def get_virtual_trades(limit: int = Query(50, ge=1, le=500)):
    """Get virtual trading history."""
    db = SessionLocal()
    try:
        trades = db.query(VirtualTrade).order_by(VirtualTrade.exit_time.desc()).limit(limit).all()
        return VirtualTradesResponse(
            trades=[
                VirtualTradeResponse(
                    id=t.id,
                    symbol=t.symbol,
                    direction=t.direction,
                    entry_price=t.entry_price,
                    exit_price=t.exit_price,
                    quantity=t.quantity,
                    entry_time=t.entry_time,
                    exit_time=t.exit_time,
                    pnl=t.pnl,
                    pnl_pct=t.pnl_pct,
                    fees=t.fees,
                )
                for t in trades
            ]
        )
    finally:
        db.close()


@app.get("/api/virtual/positions", response_model=VirtualPositionsResponse)
def get_virtual_positions():
    """Get current open virtual positions."""
    db = SessionLocal()
    try:
        positions = db.query(VirtualPosition).all()
        position_responses = []
        for pos in positions:
            # Calculate unrealized P&L
            if pos.direction == "LONG":
                unrealized_pnl = (pos.current_price - pos.entry_price) * pos.quantity
            else:  # SHORT
                unrealized_pnl = (pos.entry_price - pos.current_price) * pos.quantity
            
            entry_value = pos.entry_price * pos.quantity
            unrealized_pnl_pct = (unrealized_pnl / entry_value) * 100 if entry_value > 0 else 0
            
            position_responses.append(
                VirtualPositionResponse(
                    id=pos.id,
                    symbol=pos.symbol,
                    direction=pos.direction,
                    entry_price=pos.entry_price,
                    current_price=pos.current_price,
                    quantity=pos.quantity,
                    entry_time=pos.entry_time,
                    unrealized_pnl=unrealized_pnl,
                    unrealized_pnl_pct=unrealized_pnl_pct,
                )
            )
        return VirtualPositionsResponse(positions=position_responses)
    finally:
        db.close()


@app.post("/api/virtual/reset")
def reset_virtual_account():
    """Reset the virtual trading account to starting balance and clear all trades/positions."""
    db = SessionLocal()
    try:
        account = VirtualTradingService.reset_account(db)
        return {"message": "Virtual account reset successfully", "balance": account.balance}
    finally:
        db.close()


