"""
POC (Point of Control) and confluence tracking components
"""
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Tuple


class POCTracker:
    """Tracks Point of Control (POC) across multiple bars for confluence detection"""

    def __init__(self, lookback_bars: int, tick_size: Decimal):
        self.lookback_bars = lookback_bars
        self.tick_size = tick_size
        self.poc_history: deque = deque(maxlen=lookback_bars)
        self.confluence_levels: Dict[Decimal, int] = {}

    def add_poc(self, poc_price: Decimal, volume: Decimal):
        """Add a new POC from a completed bar"""
        normalized_poc = self._normalize_price(poc_price)

        # Add to history
        self.poc_history.append({
            "price": normalized_poc,
            "volume": volume,
            "timestamp": datetime.now(timezone.utc)
        })

        # Update confluence tracking
        self._update_confluence()

    def _normalize_price(self, price: Decimal) -> Decimal:
        """Normalize price to tick size bucket"""
        return (price // self.tick_size) * self.tick_size

    def _update_confluence(self):
        """Update confluence levels based on POC history"""
        self.confluence_levels.clear()

        for poc_data in self.poc_history:
            price = poc_data["price"]
            self.confluence_levels[price] = self.confluence_levels.get(price, 0) + 1

    def get_strongest_levels(self, top_n: int = 3) -> List[Tuple[Decimal, int]]:
        """Get the strongest confluence levels"""
        sorted_levels = sorted(
            self.confluence_levels.items(),
            key=lambda x: x[1],
            reverse=True
        )
        return sorted_levels[:top_n]

    def get_confluence_score(self, price: Decimal) -> int:
        """Get confluence score for a specific price level"""
        normalized = self._normalize_price(price)
        return self.confluence_levels.get(normalized, 0)
