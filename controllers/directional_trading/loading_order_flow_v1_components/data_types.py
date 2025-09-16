"""
Data types for Loading Order Flow V1 Controller
"""
import asyncio
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional


@dataclass
class VolumeProfile:
    """Volume profile with configurable price buckets"""
    tick_size: Decimal  # Size of price buckets (e.g., 1.0 for $1)
    volume_by_price: Dict[Decimal, Decimal] = field(default_factory=dict)
    delta_by_price: Dict[Decimal, Decimal] = field(default_factory=dict)  # buy - sell volume

    def normalize_price(self, price: Decimal) -> Decimal:
        """Round price to nearest tick_size bucket"""
        return (price // self.tick_size) * self.tick_size

    @property
    def poc(self) -> Optional[Decimal]:
        """Point of Control - price level with highest volume"""
        if not self.volume_by_price:
            return None
        return max(self.volume_by_price.items(), key=lambda x: x[1])[0]

    @property
    def poc_volume(self) -> Optional[Decimal]:
        """Volume at the Point of Control"""
        if not self.volume_by_price:
            return None
        return max(self.volume_by_price.values())

    def get_value_area(self, percentage: Decimal = Decimal("0.70")) -> tuple[Optional[Decimal], Optional[Decimal]]:
        """Calculate value area (default 70% of volume)"""
        if not self.volume_by_price:
            return None, None

        total_volume = sum(self.volume_by_price.values())
        target_volume = total_volume * percentage

        # Sort prices by volume (descending)
        sorted_prices = sorted(self.volume_by_price.items(), key=lambda x: x[1], reverse=True)

        accumulated_volume = Decimal("0")
        value_area_prices = []

        for price, volume in sorted_prices:
            accumulated_volume += volume
            value_area_prices.append(price)
            if accumulated_volume >= target_volume:
                break

        if value_area_prices:
            return min(value_area_prices), max(value_area_prices)
        return None, None

    def update(self, price: Decimal, volume: Decimal, volume_delta: Decimal):
        """
        Update volume profile with a new trade

        Args:
            price: Trade price
            volume: Trade volume
            volume_delta: Volume delta (positive for buy, negative for sell)
        """
        normalized_price = self.normalize_price(price)

        # Update volume at this price level
        self.volume_by_price[normalized_price] = self.volume_by_price.get(normalized_price, Decimal("0")) + volume
        self.delta_by_price[normalized_price] = self.delta_by_price.get(normalized_price, Decimal("0")) + volume_delta


@dataclass
class POCConfluence:
    """Track POC levels across multiple bars for confluence"""
    price_level: Decimal
    occurrences: int = 0
    total_volume: Decimal = Decimal("0")
    bar_indices: List[int] = field(default_factory=list)
    last_seen_timestamp: Optional[float] = None
    average_volume: Decimal = Decimal("0")


@dataclass
class RangeBar:
    """Price range bar OHLC data with volume profile"""
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    timestamp_start: float
    timestamp_end: Optional[float] = None
    trade_count: int = 0
    volume_profile: Optional[VolumeProfile] = None

    def __post_init__(self):
        """Validate OHLC relationships"""
        if self.high < self.low:
            raise ValueError(f"High ({self.high}) cannot be less than low ({self.low})")
        if not (self.low <= self.open <= self.high):
            raise ValueError(f"Open ({self.open}) must be between low and high")
        if not (self.low <= self.close <= self.high):
            raise ValueError(f"Close ({self.close}) must be between low and high")


@dataclass
class CVDCandle:
    """CVD OHLC data for a range bar with validation"""
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal

    def __post_init__(self):
        """Validate CVD candle data"""
        if self.high < self.low:
            raise ValueError(f"CVD High ({self.high}) cannot be less than low ({self.low})")


@dataclass
class TradingPairData:
    """Tracks all data for a single trading pair with thread-safe operations"""
    # Range bar settings
    range_size: Decimal
    volume_tick_size: Decimal = Decimal("1.0")
    current_range_low: Optional[Decimal] = None
    current_range_high: Optional[Decimal] = None

    # Current range bar
    current_bar: Optional[RangeBar] = None

    # CVD tracking
    cumulative_cvd: Decimal = Decimal("0")
    current_bar_cvd: Decimal = Decimal("0")
    current_cvd_candle: Optional[CVDCandle] = None

    # Historical data with configurable size
    completed_bars: deque = field(default_factory=lambda: deque(maxlen=1000))
    completed_cvd_candles: deque = field(default_factory=lambda: deque(maxlen=1000))

    # POC confluence tracking
    poc_tracker: Optional[Any] = None  # Will be POCTracker instance

    # State tracking
    first_trade_processed: bool = False
    last_reset_timestamp: float = 0
    last_completed_bar_info: Optional[str] = None

    # Metrics
    total_volume_processed: Decimal = field(default_factory=lambda: Decimal("0"))
    total_trades_processed: int = 0

    def __post_init__(self):
        """Initialize lock for thread safety"""
        self._lock = asyncio.Lock()
