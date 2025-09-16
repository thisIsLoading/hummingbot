import asyncio
import logging
from decimal import Decimal
from typing import List

from pydantic import Field, field_validator

# Import components from our modules
from controllers.directional_trading.loading_order_flow_v1_components import (
    ConfigurationError,
    MarketDataManager,
    StatusFormatter,
)
from hummingbot.core.event.event_forwarder import SourceInfoEventForwarder
from hummingbot.core.event.events import OrderBookEvent, OrderBookTradeEvent
from hummingbot.strategy_v2.controllers.simple_trading_controller_base import (
    SimpleTradingControllerBase,
    SimpleTradingControllerConfigBase,
)
from hummingbot.strategy_v2.executors.data_types import ConnectorPair

# ============================================================================
# CONFIGURATION
# ============================================================================


class LoadingOrderFlowV1Config(SimpleTradingControllerConfigBase):
    """
    Configuration for CVD Range Bar Controller with validation
    """
    controller_name: str = "loading_order_flow_v1"

    # Range bar configuration
    range_size: Decimal = Field(
        default=Decimal("20"),
        gt=0,
        json_schema_extra={
            "prompt": "Enter the range bar size in quote currency (e.g., 20 for $20 ranges): ",
            "prompt_on_new": True,
            "is_updatable": True
        }
    )

    # Historical data limits
    max_bars_history: int = Field(
        default=1000,
        gt=0,
        le=10000,
        json_schema_extra={
            "prompt": "Maximum number of historical bars to keep (1-10000): ",
            "prompt_on_new": False,
            "is_updatable": True
        }
    )

    # Volume profile settings (always enabled - core functionality)

    volume_tick_size: Decimal = Field(
        default=Decimal("1.0"),
        gt=0,
        json_schema_extra={
            "prompt": "Enter volume profile tick size in quote currency (e.g., 1 for $1 buckets): ",
            "prompt_on_new": True,
            "is_updatable": False
        }
    )

    # POC confluence uses all available history (up to max_bars_history)

    # Processing timeout
    processing_timeout: float = Field(
        default=1.0,
        gt=0,
        le=10.0,
        json_schema_extra={
            "prompt": "Trade processing timeout in seconds (0.1-10.0): ",
            "prompt_on_new": False,
            "is_updatable": True
        }
    )

    @field_validator('range_size')
    @classmethod
    def validate_range_size(cls, v):
        """Ensure range size is positive and reasonable"""
        if v <= 0:
            raise ValueError("Range size must be positive")
        if v > Decimal("10000"):
            raise ValueError("Range size seems unreasonably large (>10000)")
        return v

    def update_markets(self, markets):
        """Add our connector and trading pair to the markets"""
        return markets.add_or_update(self.connector_name, self.trading_pair)


# ============================================================================
# MAIN CONTROLLER
# ============================================================================

class LoadingOrderFlowV1Controller(SimpleTradingControllerBase):
    """
    Enterprise-grade CVD (Cumulative Volume Delta) Range Bar Controller
    Tracks range bars and CVD for monitoring order flow with proper error handling,
    validation, and thread safety.
    """

    def __init__(self, config: LoadingOrderFlowV1Config, *args, **kwargs):
        """Initialize controller with validation"""
        # Validate configuration
        self._validate_config(config)

        self.config = config
        super().__init__(config, *args, **kwargs)

        # Initialize market data manager
        self.market_data_manager = MarketDataManager(config)

        # Initialize status formatter
        self.status_formatter = StatusFormatter()

        # Set up event handling
        self.trade_event_forwarder = SourceInfoEventForwarder(self._process_public_trade)
        self._subscribed = False
        self._subscription_lock = asyncio.Lock()

        # Set logging level appropriately
        self.logger().setLevel(logging.INFO)

        # Initialize market data provider
        self.market_data_provider.initialize_rate_sources([
            ConnectorPair(
                connector_name=config.connector_name,
                trading_pair=config.trading_pair
            )
        ])

        # Subscribe to trade events
        self._subscribe_to_trade_events()

        self.logger().info(
            f"CVD Controller initialized - Range: {config.range_size}, "
            f"Pair: {config.trading_pair}, Tick Size: {config.volume_tick_size}"
        )

    def _validate_config(self, config: LoadingOrderFlowV1Config):
        """Validate configuration on initialization"""
        if config.range_size <= 0:
            raise ConfigurationError("Range size must be positive")

        if not config.connector_name:
            raise ConfigurationError("Connector name is required")

        if not config.trading_pair:
            raise ConfigurationError("Trading pair is required")

    def _subscribe_to_trade_events(self):
        """Subscribe to order book trade events with thread safety"""
        if self._subscribed:
            return

        connector = self.market_data_provider.connectors.get(self.config.connector_name)

        if connector and connector.order_books:
            for trading_pair, order_book in connector.order_books.items():
                if trading_pair == self.config.trading_pair:
                    order_book.add_listener(OrderBookEvent.TradeEvent, self.trade_event_forwarder)
                    self._subscribed = True
                    self.logger().info(f"Subscribed to trade events for {trading_pair}")
                    break

    def _process_public_trade(self, event_tag: int, market, event: OrderBookTradeEvent):
        """Process trade events with proper error handling"""
        try:
            # Filter for our trading pair
            if event.trading_pair != self.config.trading_pair:
                return

            # Process the trade asynchronously using MarketDataManager
            asyncio.create_task(self._process_trade_async(event))

        except Exception as e:
            self.logger().error(f"Unexpected error processing trade: {e}", exc_info=True)

    async def _process_trade_async(self, event: OrderBookTradeEvent):
        """Process trade using MarketDataManager"""
        try:
            # Let MarketDataManager handle all the processing
            result = await self.market_data_manager.process_trade(
                price=event.price,
                volume=event.amount,
                timestamp=event.timestamp,
                event=event
            )

            # Log completed bar if one was finished (debug level to reduce noise)
            if result.get("completed_bar_info"):
                self.logger().debug(result["completed_bar_info"])

        except asyncio.TimeoutError:
            self.logger().warning(f"Timeout processing trade: {event.trading_pair} @ {event.price}")
            # Don't crash, just skip this trade
        except Exception as e:
            self.logger().error(f"Error processing trade: {e}", exc_info=True)
            # Log but continue processing future trades

    async def update_processed_data(self):
        """Update processed data for strategy use"""
        # Always check and re-subscribe if needed (in case of network reconnection)
        async with self._subscription_lock:
            connector = self.market_data_provider.connectors.get(self.config.connector_name)
            if connector and connector.order_books:
                # Check if we're still subscribed
                order_book = connector.order_books.get(self.config.trading_pair)
                if order_book and not self._is_subscribed_to_order_book(order_book):
                    self.logger().warning(f"Lost subscription to {self.config.trading_pair}, resubscribing...")
                    self._subscribed = False
                    self._subscribe_to_trade_events()

        # Get processed data from MarketDataManager
        try:
            self.processed_data = await self.market_data_manager.get_processed_data()
        except Exception as e:
            self.logger().error(f"Error updating processed data: {e}")
            # Return last known good data if available
            if not hasattr(self, 'processed_data'):
                self.processed_data = {"signal": 0, "cvd": 0, "completed_bars": 0}

    def _is_subscribed_to_order_book(self, order_book) -> bool:
        """Check if we're subscribed to order book trade events"""
        # Check if our forwarder is in the order book's trade event listeners
        try:
            listeners = order_book.get_listeners(OrderBookEvent.TradeEvent)
            return self.trade_event_forwarder in listeners
        except Exception:
            # If we can't check, assume we're not subscribed
            return False

    def to_format_status(self) -> List[str]:
        """Format status for display using StatusFormatter"""
        status_data = self.market_data_manager.get_status_data()
        return self.status_formatter.format_status(self.config, status_data)
