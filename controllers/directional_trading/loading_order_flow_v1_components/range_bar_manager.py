"""
Enhanced range bar management with state tracking
"""
from collections import deque
from decimal import Decimal
from typing import List, Optional, Tuple

from controllers.directional_trading.loading_order_flow_v1_components.data_types import RangeBar, VolumeProfile
from controllers.directional_trading.loading_order_flow_v1_components.exceptions import ConfigurationError


class RangeBarBuilder:
    """Builds range bars from trade data"""

    def __init__(self, range_size: Decimal):
        if range_size <= 0:
            raise ConfigurationError("Range size must be positive")
        self.range_size = range_size

    def should_create_new_bar(self, current_bar: Optional[RangeBar], price: Decimal) -> bool:
        """Check if price movement warrants a new range bar"""
        if current_bar is None:
            return True

        # Check if adding this price would exceed the range size
        # Calculate what the new high/low would be with this price
        potential_high = max(current_bar.high, price)
        potential_low = min(current_bar.low, price)
        potential_range = potential_high - potential_low

        # Create new bar if the range would exceed our target
        return potential_range >= self.range_size

    def create_bar(self, price: Decimal, volume: Decimal, timestamp: float) -> RangeBar:
        """Create a new range bar"""
        return RangeBar(
            open=price,
            high=price,
            low=price,
            close=price,
            volume=volume,
            timestamp_start=timestamp,
            trade_count=1
        )

    def update_bar(self, bar: RangeBar, price: Decimal, volume: Decimal) -> None:
        """Update existing range bar with new trade"""
        bar.high = max(bar.high, price)
        bar.low = min(bar.low, price)
        bar.close = price
        bar.volume += volume
        bar.trade_count += 1


class RangeBarManager:
    """Manages range bar lifecycle, state, and boundaries"""

    def __init__(self, range_size: Decimal, max_history: int = 1000, volume_tick_size: Decimal = Decimal("1.0")):
        """
        Initialize range bar manager

        Args:
            range_size: Size of each range bar in quote currency
            max_history: Maximum number of historical bars to keep
            volume_tick_size: Tick size for volume profile buckets
        """
        self.range_size = range_size
        self.volume_tick_size = volume_tick_size
        self.builder = RangeBarBuilder(range_size)

        # Current bar state
        self.current_bar: Optional[RangeBar] = None
        self.current_range_low: Optional[Decimal] = None
        self.current_range_high: Optional[Decimal] = None

        # Historical data
        self.completed_bars: deque = deque(maxlen=max_history)

        # State tracking
        self.first_trade_processed = False
        self.last_completed_bar_info: Optional[str] = None

    def process_trade(self, price: Decimal, volume: Decimal, timestamp: float) -> Tuple[bool, Optional[RangeBar]]:
        """
        Process a trade and update range bars

        Args:
            price: Trade price
            volume: Trade volume
            timestamp: Trade timestamp

        Returns:
            Tuple of (is_new_bar, completed_bar)
            - is_new_bar: True if a new bar was created
            - completed_bar: The completed bar if one was finished, None otherwise
        """
        completed_bar = None

        # First trade initialization
        if not self.first_trade_processed:
            self._initialize_first_bar(price, volume, timestamp)
            return True, None

        # Check if current bar exists (defensive)
        if self.current_bar is None:
            self._create_new_bar(price, volume, timestamp)
            return True, None

        # Check if new bar needed
        if self.builder.should_create_new_bar(self.current_bar, price):
            completed_bar = self._complete_current_bar(timestamp)
            self._create_new_bar(price, volume, timestamp)
            return True, completed_bar
        else:
            # Update existing bar
            self.builder.update_bar(self.current_bar, price, volume)
            # Update range bounds to reflect actual bar range
            self._update_range_bounds()
            return False, None

    def _initialize_first_bar(self, price: Decimal, volume: Decimal, timestamp: float):
        """Initialize the first range bar"""
        self._set_range_bounds(price)
        self.current_bar = self.builder.create_bar(price, volume, timestamp)
        self.current_bar.volume_profile = VolumeProfile(tick_size=self.volume_tick_size)
        self.first_trade_processed = True

    def _create_new_bar(self, price: Decimal, volume: Decimal, timestamp: float):
        """Create a new range bar"""
        self._set_range_bounds(price)
        self.current_bar = self.builder.create_bar(price, volume, timestamp)
        self.current_bar.volume_profile = VolumeProfile(tick_size=self.volume_tick_size)

    def _set_range_bounds(self, price: Decimal):
        """Set the range boundaries for current bar based on first price"""
        # Initial range centered on first price
        half_range = self.range_size / 2
        self.current_range_low = price - half_range
        self.current_range_high = price + half_range

    def _update_range_bounds(self):
        """Update range boundaries to reflect actual bar high/low"""
        if self.current_bar:
            # Range should always encompass the actual bar's range
            # and extend to the full range_size
            bar_range = self.current_bar.high - self.current_bar.low
            remaining_range = self.range_size - bar_range

            if remaining_range > 0:
                # Distribute remaining range equally above/below
                half_remaining = remaining_range / 2
                self.current_range_low = self.current_bar.low - half_remaining
                self.current_range_high = self.current_bar.high + half_remaining
            else:
                # Bar already at or exceeding range
                self.current_range_low = self.current_bar.low
                self.current_range_high = self.current_bar.high

    def _complete_current_bar(self, timestamp: float) -> Optional[RangeBar]:
        """
        Complete the current bar and add to history

        Args:
            timestamp: Completion timestamp

        Returns:
            The completed bar
        """
        if self.current_bar:
            self.current_bar.timestamp_end = timestamp
            self.completed_bars.append(self.current_bar)
            self._update_last_completed_info()
            return self.current_bar
        return None

    def _update_last_completed_info(self):
        """Update the formatted string for last completed bar"""
        if self.current_bar:
            bar_duration = (self.current_bar.timestamp_end or 0) - self.current_bar.timestamp_start
            poc_info = ""

            if self.current_bar.volume_profile and self.current_bar.volume_profile.poc:
                poc_info = f" | POC: {self.current_bar.volume_profile.poc:.2f}"

            self.last_completed_bar_info = (
                f"[COMPLETED] Price: {self.current_bar.open:.2f}->{self.current_bar.close:.2f} | "
                f"Vol: {self.current_bar.volume:.4f} | Trades: {self.current_bar.trade_count}{poc_info} | "
                f"Duration: {bar_duration:.1f}s"
            )

    def get_current_bar(self) -> Optional[RangeBar]:
        """Get the current active bar"""
        return self.current_bar

    def get_completed_bars(self) -> List[RangeBar]:
        """Get list of completed bars"""
        return list(self.completed_bars)

    def get_range_bounds(self) -> Tuple[Optional[Decimal], Optional[Decimal]]:
        """Get current range boundaries"""
        return self.current_range_low, self.current_range_high

    def get_range_usage_pct(self) -> float:
        """Calculate percentage of range used by current bar"""
        if self.current_bar and self.range_size > 0:
            price_range_used = self.current_bar.high - self.current_bar.low
            return float(price_range_used / self.range_size * 100)
        return 0.0
