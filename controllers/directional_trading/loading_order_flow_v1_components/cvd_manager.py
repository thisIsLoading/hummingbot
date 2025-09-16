"""
CVD (Cumulative Volume Delta) state management
"""
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import List, Optional

from controllers.directional_trading.loading_order_flow_v1_components.data_types import CVDCandle
from controllers.directional_trading.loading_order_flow_v1_components.exceptions import InvalidTradeDataError
from hummingbot.core.event.events import OrderBookTradeEvent


class CVDCalculator:
    """Handles CVD calculations with proper validation"""

    @staticmethod
    def calculate_volume_delta(event: OrderBookTradeEvent) -> Decimal:
        """Calculate volume delta from trade event"""
        try:
            volume = Decimal(str(event.amount))
            if volume < 0:
                raise InvalidTradeDataError(f"Negative volume: {volume}")

            # Determine if buy or sell
            is_buy = event.type.name == "BUY"
            return volume if is_buy else -volume

        except (InvalidOperation, AttributeError) as e:
            raise InvalidTradeDataError(f"Invalid trade data: {e}")


class CVDManager:
    """Manages CVD state, candles, and resets"""

    def __init__(self, max_history: int = 1000):
        """
        Initialize CVD manager

        Args:
            max_history: Maximum number of historical CVD candles to keep
        """
        self.cumulative_cvd: Decimal = Decimal("0")
        self.current_bar_cvd: Decimal = Decimal("0")
        self.current_cvd_candle: Optional[CVDCandle] = None
        self.completed_cvd_candles: deque = deque(maxlen=max_history)
        self.last_reset_timestamp: float = 0
        self._calculator = CVDCalculator()

    def process_trade(self, event: OrderBookTradeEvent, is_new_bar: bool) -> Decimal:
        """
        Process a trade and update CVD

        Args:
            event: Trade event from order book
            is_new_bar: Whether this trade starts a new bar

        Returns:
            Volume delta for this trade
        """
        # Calculate delta
        volume_delta = self._calculator.calculate_volume_delta(event)

        # Update cumulative CVD
        self.cumulative_cvd += volume_delta

        # Update bar CVD
        if is_new_bar:
            self.current_bar_cvd = volume_delta
        else:
            self.current_bar_cvd += volume_delta

        # Update CVD candle
        self._update_cvd_candle()

        return volume_delta

    def _update_cvd_candle(self):
        """Update or create CVD candle OHLC values"""
        if self.current_cvd_candle is None:
            # Create new candle with continuity
            if self.completed_cvd_candles:
                # New candle opens at close of previous
                cvd_open = self.completed_cvd_candles[-1].close
            else:
                # First candle - check if we have any CVD from previous trades
                # If this is truly the first trade ever, open should be 0
                # Otherwise open at CVD before current bar's trades
                if self.cumulative_cvd == self.current_bar_cvd:
                    # First trade ever - CVD starts at 0
                    cvd_open = Decimal("0")
                else:
                    # We have previous CVD, open at that value
                    cvd_open = self.cumulative_cvd - self.current_bar_cvd

            self.current_cvd_candle = CVDCandle(
                open=cvd_open,
                high=self.cumulative_cvd,
                low=self.cumulative_cvd,
                close=self.cumulative_cvd
            )
        else:
            # Update existing candle
            self.current_cvd_candle.high = max(self.current_cvd_candle.high, self.cumulative_cvd)
            self.current_cvd_candle.low = min(self.current_cvd_candle.low, self.cumulative_cvd)
            self.current_cvd_candle.close = self.cumulative_cvd

    def complete_candle(self) -> Optional[CVDCandle]:
        """
        Complete current CVD candle and start new one

        Returns:
            Completed CVD candle or None if no candle to complete
        """
        if self.current_cvd_candle:
            completed = self.current_cvd_candle
            self.completed_cvd_candles.append(completed)
            self.current_cvd_candle = None
            return completed
        return None

    def check_and_reset(self, timestamp: float) -> bool:
        """
        Check if CVD should be reset at midnight UTC

        Args:
            timestamp: Current trade timestamp

        Returns:
            True if CVD was reset, False otherwise
        """
        last_reset_date = datetime.fromtimestamp(self.last_reset_timestamp, tz=timezone.utc).date()
        current_date = datetime.fromtimestamp(timestamp, tz=timezone.utc).date()

        if current_date > last_reset_date:
            self.reset()
            self.last_reset_timestamp = timestamp
            return True
        return False

    def reset(self):
        """Reset CVD to zero (e.g., at midnight)"""
        self.cumulative_cvd = Decimal("0")
        self.current_bar_cvd = Decimal("0")
        # Note: We don't reset candles or history

    def get_cumulative_cvd(self) -> Decimal:
        """Get current cumulative CVD"""
        return self.cumulative_cvd

    def get_current_bar_cvd(self) -> Decimal:
        """Get CVD for current bar only"""
        return self.current_bar_cvd

    def get_completed_candles(self) -> List[CVDCandle]:
        """Get list of completed CVD candles"""
        return list(self.completed_cvd_candles)
