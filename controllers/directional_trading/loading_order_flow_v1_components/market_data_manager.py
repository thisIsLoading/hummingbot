"""
Market data state management - encapsulates all market data state
"""
import asyncio
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from controllers.directional_trading.loading_order_flow_v1_components.cvd_manager import CVDManager
from controllers.directional_trading.loading_order_flow_v1_components.data_types import CVDCandle, RangeBar
from controllers.directional_trading.loading_order_flow_v1_components.metrics import MetricsCollector
from controllers.directional_trading.loading_order_flow_v1_components.poc_tracker import POCTracker
from controllers.directional_trading.loading_order_flow_v1_components.range_bar_manager import RangeBarManager
from controllers.directional_trading.loading_order_flow_v1_components.validators import TradeValidator
from hummingbot.core.event.events import OrderBookTradeEvent


class MarketDataManager:
    """
    Encapsulates and manages all market data state
    Provides clean interface for the controller
    """

    def __init__(self, config):
        """
        Initialize market data manager with configuration

        Args:
            config: Controller configuration object
        """
        # Core configuration
        self.range_size = config.range_size
        self.volume_tick_size = config.volume_tick_size
        self.max_bars_history = config.max_bars_history
        self.processing_timeout = getattr(config, 'processing_timeout', 1.0)  # Default 1 second

        # Initialize components
        self.validator = TradeValidator()
        self.cvd_manager = CVDManager(max_history=config.max_bars_history)
        self.bar_manager = RangeBarManager(
            range_size=config.range_size,
            max_history=config.max_bars_history,
            volume_tick_size=config.volume_tick_size
        )
        self.poc_tracker = POCTracker(
            lookback_bars=config.max_bars_history,
            tick_size=config.volume_tick_size
        )
        self.metrics = MetricsCollector(enabled=True)

        # State tracking
        self.total_volume_processed = Decimal("0")
        self.total_trades_processed = 0
        self.last_completed_bar_info: Optional[str] = None

        # Thread safety
        self._lock = asyncio.Lock()

    async def process_trade(self, price: Any, volume: Any, timestamp: Any, event: OrderBookTradeEvent) -> Dict[str, Any]:
        """
        Process a trade through the entire pipeline

        Args:
            price: Raw price from trade event
            volume: Raw volume from trade event
            timestamp: Trade timestamp
            event: Original trade event

        Returns:
            Dictionary with processing results
        """
        # Use timeout to prevent lock deadlock
        try:
            async with asyncio.timeout(self.processing_timeout):
                async with self._lock:
                    # Validate inputs
                    validated_price, validated_volume, validated_timestamp = self.validator.validate_trade(
                        price, volume, timestamp
                    )

                    # Check for daily CVD reset
                    if self.cvd_manager.check_and_reset(validated_timestamp):
                        self.metrics.record_event("cvd_reset")

                    # Process through bar manager
                    is_new_bar, completed_bar = self.bar_manager.process_trade(
                        validated_price, validated_volume, validated_timestamp
                    )

                    # If bar completed, complete CVD candle BEFORE processing new trade
                    completed_cvd = None
                    if completed_bar:
                        completed_cvd = self.cvd_manager.complete_candle()

                    # Process through CVD manager (will create new candle if needed)
                    volume_delta = self.cvd_manager.process_trade(event, is_new_bar)

                    # Update volume profile if bar exists
                    current_bar = self.bar_manager.get_current_bar()
                    if current_bar and current_bar.volume_profile:
                        current_bar.volume_profile.update(validated_price, validated_volume, volume_delta)

                    # Handle bar completion with the completed CVD
                    if completed_bar:
                        self._handle_bar_completion_with_cvd(completed_bar, completed_cvd, validated_timestamp)

                    # Update global metrics
                    self.total_volume_processed += validated_volume
                    self.total_trades_processed += 1
                    self.metrics.record_trade()

                    return {
                        "is_new_bar": is_new_bar,
                        "completed_bar": completed_bar,
                        "volume_delta": volume_delta,
                        "current_cvd": self.cvd_manager.get_cumulative_cvd(),
                        "completed_bar_info": self.last_completed_bar_info if completed_bar else None
                    }

        except asyncio.TimeoutError:
            self.metrics.record_error()
            raise Exception("Trade processing timeout - possible deadlock detected")
        except Exception:
            self.metrics.record_error()
            raise

    def _handle_bar_completion_with_cvd(self, completed_bar: RangeBar, completed_cvd: Optional[CVDCandle], timestamp: float):
        """
        Handle tasks when a bar completes

        Args:
            completed_bar: The completed range bar
            completed_cvd: The completed CVD candle
            timestamp: Completion timestamp
        """
        # Track POC if volume profile exists
        if completed_bar.volume_profile and completed_bar.volume_profile.poc:
            poc_price = completed_bar.volume_profile.poc
            poc_volume = completed_bar.volume_profile.poc_volume or Decimal("0")
            self.poc_tracker.add_poc(poc_price, poc_volume)

        # Update display info
        self._update_completed_bar_info(completed_bar, completed_cvd)

        # Record metrics
        self.metrics.record_bar_completion()

    def _update_completed_bar_info(self, bar: RangeBar, cvd_candle: Optional[CVDCandle]):
        """Update formatted string for last completed bar"""
        if bar and cvd_candle:
            bar_duration = (bar.timestamp_end or 0) - bar.timestamp_start
            poc_info = ""

            if bar.volume_profile and bar.volume_profile.poc:
                poc_info = f" | POC: {bar.volume_profile.poc:.2f}"

            self.last_completed_bar_info = (
                f"[COMPLETED] Price: {bar.open:.2f}->{bar.close:.2f} | "
                f"CVD: {cvd_candle.open:.4f}->{cvd_candle.close:.4f} | "
                f"Vol: {bar.volume:.4f} | Trades: {bar.trade_count}{poc_info} | "
                f"Duration: {bar_duration:.1f}s"
            )

    # Clean interface methods for controller

    def get_current_bar(self) -> Optional[RangeBar]:
        """Get current active range bar"""
        return self.bar_manager.get_current_bar()

    def get_completed_bars(self) -> List[RangeBar]:
        """Get list of completed range bars"""
        return self.bar_manager.get_completed_bars()

    def get_cumulative_cvd(self) -> Decimal:
        """Get current cumulative CVD"""
        return self.cvd_manager.get_cumulative_cvd()

    def get_completed_cvd_candles(self) -> List[CVDCandle]:
        """Get list of completed CVD candles"""
        return self.cvd_manager.get_completed_candles()

    def get_range_bounds(self) -> Tuple[Optional[Decimal], Optional[Decimal]]:
        """Get current range boundaries"""
        return self.bar_manager.get_range_bounds()

    def get_poc_confluence_levels(self, top_n: int = 3) -> List[Tuple[Decimal, int]]:
        """Get strongest POC confluence levels"""
        return self.poc_tracker.get_strongest_levels(top_n)

    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get metrics summary"""
        summary = self.metrics.get_summary()
        summary.update({
            "total_volume_processed": float(self.total_volume_processed),
            "total_trades_processed": self.total_trades_processed,
            "completed_bars": len(self.get_completed_bars()),
            "current_cvd": float(self.get_cumulative_cvd())
        })
        return summary

    async def get_processed_data(self) -> Dict[str, Any]:
        """Get processed data for strategy use"""
        async with self._lock:
            processed_data = {
                "signal": 0,  # No trading signals for monitoring controller
                "cvd": float(self.get_cumulative_cvd()),
                "completed_bars": len(self.get_completed_bars()),
                "total_volume": float(self.total_volume_processed),
                "total_trades": self.total_trades_processed,
                "metrics": self.metrics.get_summary(),
            }

            # Add POC confluence data
            strongest_levels = self.poc_tracker.get_strongest_levels(3)
            processed_data["poc_confluence"] = [
                {"price": float(price), "count": count}
                for price, count in strongest_levels
            ]

            return processed_data

    def get_status_data(self) -> Dict[str, Any]:
        """Get all data needed for status display"""
        current_bar = self.get_current_bar()
        range_low, range_high = self.get_range_bounds()

        status_data = {
            "completed_bars": len(self.get_completed_bars()),
            "total_volume": float(self.total_volume_processed),
            "total_trades": self.total_trades_processed,
            "last_completed_bar_info": self.last_completed_bar_info,
            "errors_count": self.metrics.get_summary().get("errors_count", 0)
        }

        # Add current bar data if available
        if current_bar:
            price_range_used = current_bar.high - current_bar.low
            range_pct = (price_range_used / self.range_size * 100) if self.range_size > 0 else 0

            status_data["current_bar"] = {
                "range_low": range_low,
                "range_high": range_high,
                "price": current_bar.close,
                "cvd": self.get_cumulative_cvd(),
                "range_used": price_range_used,
                "range_pct": range_pct,
                "volume": current_bar.volume,
                "trade_count": current_bar.trade_count
            }

            # Add POC data if available
            if current_bar.volume_profile:
                poc_price, poc_volume = self._calculate_poc(current_bar.volume_profile)
                if poc_price:
                    status_data["current_poc"] = {
                        "price": poc_price,
                        "volume": poc_volume
                    }

        # Add POC confluence
        poc_levels = self.get_poc_confluence_levels(2)
        if poc_levels:
            status_data["poc_confluence"] = [
                {"price": price, "count": count}
                for price, count in poc_levels
            ]

        return status_data

    def _calculate_poc(self, volume_profile) -> Tuple[Optional[Decimal], Decimal]:
        """Calculate Point of Control (price with highest volume)"""
        if not volume_profile.volume_by_price:
            return None, Decimal("0")

        poc_price = max(volume_profile.volume_by_price.items(), key=lambda x: x[1])
        return poc_price[0], poc_price[1]
