from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel


class Timeframe(str, Enum):
    m15 = "15m"
    h1 = "1h"


class SignalType(str, Enum):
    NO_TRADE = "NO_TRADE"
    LONG_ENTRY = "LONG_ENTRY"
    LONG_EXIT = "LONG_EXIT"
    SHORT_ENTRY = "SHORT_ENTRY"
    SHORT_EXIT = "SHORT_EXIT"


class Candle(BaseModel):
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class TradeSignal(BaseModel):
    symbol: str
    timeframe: Timeframe
    signal: SignalType
    price: float
    generated_at: datetime
    reason: str
    extra: Optional[dict] = None


class SignalHistoryResponse(BaseModel):
    signals: List[TradeSignal]


class ChartCandle(BaseModel):
    """OHLC + time as Unix seconds for charting libraries."""
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class CandlesResponse(BaseModel):
    symbol: str
    timeframe: str
    candles: List[ChartCandle]


class BacktestTrade(BaseModel):
    entry_time: datetime
    exit_time: datetime
    direction: SignalType  # LONG_ENTRY or SHORT_ENTRY
    entry_price: float
    exit_price: float
    return_pct: float


class BacktestResult(BaseModel):
    symbol: str
    timeframe: Timeframe
    trades: List[BacktestTrade]
    gross_return_pct: float
    net_return_pct: float
    total_fees_pct: float
    max_drawdown_pct: float
    win_rate_pct: float
    long_win_rate_pct: float
    short_win_rate_pct: float
    num_long_trades: int
    num_short_trades: int
    num_trades: int


class VirtualTradeResponse(BaseModel):
    id: int
    symbol: str
    direction: str
    entry_price: float
    exit_price: float
    quantity: float
    entry_time: datetime
    exit_time: datetime
    pnl: float
    pnl_pct: float
    fees: float


class VirtualPositionResponse(BaseModel):
    id: int
    symbol: str
    direction: str
    entry_price: float
    current_price: float
    quantity: float
    entry_time: datetime
    unrealized_pnl: float
    unrealized_pnl_pct: float


class VirtualAccountResponse(BaseModel):
    current_balance: float
    starting_balance: float
    position_size_pct: float
    total_pnl: float
    total_return_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    total_fees: float
    max_drawdown_pct: float


class UpdatePositionSizeRequest(BaseModel):
    position_size_pct: float  # Percentage (e.g., 50.0 for 50%)


class VirtualTradesResponse(BaseModel):
    trades: List[VirtualTradeResponse]


class VirtualPositionsResponse(BaseModel):
    positions: List[VirtualPositionResponse]

