from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.database import VirtualAccount, VirtualPosition, VirtualTrade
from app.models import SignalType


class VirtualTradingService:
    """Service for managing virtual/paper trading account and executing trades."""

    FEE_RATE = 0.0008  # 0.08% round-trip fee (0.04% per side)

    @staticmethod
    def get_or_create_account(db: Session) -> VirtualAccount:
        """Get the virtual trading account, creating one if it doesn't exist."""
        account = db.query(VirtualAccount).first()
        if not account:
            account = VirtualAccount(
                balance=10000.0,
                starting_balance=10000.0,
                position_size_pct=100.0  # Default to 100% position size
            )
            db.add(account)
            db.commit()
            db.refresh(account)
        else:
            # Migration: Set default position_size_pct if it doesn't exist (for existing accounts)
            if not hasattr(account, 'position_size_pct') or account.position_size_pct is None:
                account.position_size_pct = 100.0
                db.commit()
                db.refresh(account)
        return account

    @staticmethod
    def reset_account(db: Session) -> VirtualAccount:
        """Reset the virtual account to starting balance and clear all positions/trades."""
        account = VirtualTradingService.get_or_create_account(db)
        
        # Clear all positions
        db.query(VirtualPosition).delete()
        
        # Clear all trades
        db.query(VirtualTrade).delete()
        
        # Reset balance
        account.balance = account.starting_balance
        account.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(account)
        return account

    @staticmethod
    def get_current_position(db: Session, symbol: str) -> Optional[VirtualPosition]:
        """Get the current open position for a symbol (for backward compatibility)."""
        return db.query(VirtualPosition).filter(VirtualPosition.symbol == symbol).first()
    
    @staticmethod
    def get_all_positions(db: Session, symbol: str = None) -> list[VirtualPosition]:
        """Get all open positions, optionally filtered by symbol."""
        query = db.query(VirtualPosition)
        if symbol:
            query = query.filter(VirtualPosition.symbol == symbol)
        return query.all()

    @staticmethod
    def execute_trade(
        db: Session,
        symbol: str,
        signal: SignalType,
        price: float,
        signal_time: datetime,
    ) -> Optional[VirtualTrade]:
        """
        Execute a virtual trade based on a signal.
        Supports multiple concurrent positions per symbol.
        
        Returns the closed trade if a position was closed, None otherwise.
        """
        account = VirtualTradingService.get_or_create_account(db)
        all_positions = VirtualTradingService.get_all_positions(db, symbol)
        
        closed_trades = []
        
        # Handle entry signals
        if signal == SignalType.LONG_ENTRY:
            # Close any existing SHORT positions first (opposite direction)
            short_positions = [p for p in all_positions if p.direction == "SHORT"]
            for pos in short_positions:
                closed_trade = VirtualTradingService._close_position(
                    db, pos, price, signal_time
                )
                closed_trades.append(closed_trade)
            
            if closed_trades:
                db.commit()
            
            # Check if we have enough balance to open a new position
            try:
                VirtualTradingService._open_position(
                    db, account, symbol, "LONG", price, signal_time
                )
                db.commit()
            except ValueError as e:
                # Insufficient balance - skip opening new position
                print(f"Cannot open position: {e}")
        
        elif signal == SignalType.SHORT_ENTRY:
            # Close any existing LONG positions first (opposite direction)
            long_positions = [p for p in all_positions if p.direction == "LONG"]
            for pos in long_positions:
                closed_trade = VirtualTradingService._close_position(
                    db, pos, price, signal_time
                )
                closed_trades.append(closed_trade)
            
            if closed_trades:
                db.commit()
            
            # Check if we have enough balance to open a new position
            try:
                VirtualTradingService._open_position(
                    db, account, symbol, "SHORT", price, signal_time
                )
                db.commit()
            except ValueError as e:
                # Insufficient balance - skip opening new position
                print(f"Cannot open position: {e}")
        
        # Handle exit signals - close ALL positions of that direction
        elif signal == SignalType.LONG_EXIT:
            long_positions = [p for p in all_positions if p.direction == "LONG"]
            for pos in long_positions:
                closed_trade = VirtualTradingService._close_position(
                    db, pos, price, signal_time
                )
                closed_trades.append(closed_trade)
            if closed_trades:
                db.commit()
        
        elif signal == SignalType.SHORT_EXIT:
            short_positions = [p for p in all_positions if p.direction == "SHORT"]
            for pos in short_positions:
                closed_trade = VirtualTradingService._close_position(
                    db, pos, price, signal_time
                )
                closed_trades.append(closed_trade)
            if closed_trades:
                db.commit()
        
        # Update current price for ALL open positions of this symbol
        remaining_positions = VirtualTradingService.get_all_positions(db, symbol)
        for pos in remaining_positions:
            pos.current_price = price
        if remaining_positions:
            db.commit()
        
        # Return the first closed trade if any (for backward compatibility)
        return closed_trades[0] if closed_trades else None

    @staticmethod
    def _open_position(
        db: Session,
        account: VirtualAccount,
        symbol: str,
        direction: str,
        price: float,
        entry_time: datetime,
    ) -> None:
        """Open a new position. Checks available balance before opening."""
        # Calculate position size based on configured percentage
        position_size_pct = account.position_size_pct / 100.0  # Convert percentage to decimal
        position_size_usd = account.balance * position_size_pct
        
        # Ensure we have enough balance (at least for fees)
        if position_size_usd <= 0:
            raise ValueError("Insufficient balance to open position")
        
        # Calculate quantity based on price
        quantity = position_size_usd / price
        
        # Calculate entry value and fees
        entry_value = price * quantity
        entry_fee = entry_value * (VirtualTradingService.FEE_RATE / 2)
        total_cost = entry_value + entry_fee
        
        # Check if we have enough balance for this position
        if direction == "LONG":
            # For LONG: Spend money to buy, need entry_value + fee
            if account.balance < total_cost:
                raise ValueError(f"Insufficient balance. Need ${total_cost:.2f}, have ${account.balance:.2f}")
            account.balance -= total_cost
        else:  # SHORT
            # For SHORT: Sell (receive money), but we need margin/collateral
            # In simplified model, we deduct fee and use balance as collateral
            if account.balance < entry_fee:
                raise ValueError(f"Insufficient balance for fees. Need ${entry_fee:.2f}, have ${account.balance:.2f}")
            account.balance -= entry_fee
        
        position = VirtualPosition(
            symbol=symbol,
            direction=direction,
            entry_price=price,
            quantity=quantity,
            entry_time=entry_time,
            current_price=price,
        )
        db.add(position)
        account.updated_at = datetime.utcnow()

    @staticmethod
    def _close_position(
        db: Session,
        position: VirtualPosition,
        exit_price: float,
        exit_time: datetime,
    ) -> VirtualTrade:
        """Close an existing position and record the trade."""
        entry_value = position.entry_price * position.quantity
        exit_value = exit_price * position.quantity
        
        # Calculate fees
        entry_fee = entry_value * (VirtualTradingService.FEE_RATE / 2)
        exit_fee = exit_value * (VirtualTradingService.FEE_RATE / 2)
        total_fees = entry_fee + exit_fee
        
        # Calculate P&L
        if position.direction == "LONG":
            # LONG: We bought at entry_price, sell at exit_price
            gross_pnl = exit_value - entry_value
            net_pnl = gross_pnl - total_fees
            # Add back the exit value (we get money from selling)
            account = VirtualTradingService.get_or_create_account(db)
            account.balance += exit_value - exit_fee
        else:  # SHORT
            # SHORT: We sold at entry_price, buy back at exit_price
            gross_pnl = entry_value - exit_value
            net_pnl = gross_pnl - total_fees
            # Subtract the exit value (we spend money to buy back)
            account = VirtualTradingService.get_or_create_account(db)
            account.balance -= (exit_value + exit_fee)
        
        # Calculate P&L percentage
        pnl_pct = (net_pnl / entry_value) * 100 if entry_value > 0 else 0
        
        account.updated_at = datetime.utcnow()
        
        # Create trade record
        trade = VirtualTrade(
            symbol=position.symbol,
            direction=position.direction,
            entry_price=position.entry_price,
            exit_price=exit_price,
            quantity=position.quantity,
            entry_time=position.entry_time,
            exit_time=exit_time,
            pnl=net_pnl,
            pnl_pct=pnl_pct,
            fees=total_fees,
        )
        db.add(trade)
        
        # Delete position
        db.delete(position)
        
        return trade

    @staticmethod
    def get_performance_metrics(db: Session) -> dict:
        """Calculate performance metrics for the virtual account."""
        account = VirtualTradingService.get_or_create_account(db)
        trades = db.query(VirtualTrade).order_by(VirtualTrade.exit_time.desc()).all()
        
        total_pnl = account.balance - account.starting_balance
        total_return_pct = ((account.balance - account.starting_balance) / account.starting_balance) * 100
        
        winning_trades = [t for t in trades if t.pnl > 0]
        losing_trades = [t for t in trades if t.pnl < 0]
        
        win_rate = (len(winning_trades) / len(trades) * 100) if trades else 0
        
        total_fees = sum(t.fees for t in trades)
        
        # Calculate max drawdown
        peak_balance = account.starting_balance
        max_drawdown = 0.0
        running_balance = account.starting_balance
        
        for trade in sorted(trades, key=lambda t: t.exit_time):
            running_balance += trade.pnl
            if running_balance > peak_balance:
                peak_balance = running_balance
            drawdown = ((peak_balance - running_balance) / peak_balance) * 100 if peak_balance > 0 else 0
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        # Ensure position_size_pct exists (for migration compatibility)
        position_size_pct = getattr(account, 'position_size_pct', 100.0)
        if position_size_pct is None:
            position_size_pct = 100.0
        
        return {
            "current_balance": account.balance,
            "starting_balance": account.starting_balance,
            "position_size_pct": position_size_pct,
            "total_pnl": total_pnl,
            "total_return_pct": total_return_pct,
            "total_trades": len(trades),
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "win_rate_pct": win_rate,
            "total_fees": total_fees,
            "max_drawdown_pct": max_drawdown,
        }
