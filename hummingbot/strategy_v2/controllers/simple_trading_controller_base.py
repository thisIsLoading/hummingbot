from decimal import Decimal
from typing import List, Optional

from pydantic import Field

from hummingbot.core.data_type.common import OrderType, PriceType, TradeType
from hummingbot.strategy_v2.controllers.controller_base import ControllerBase, ControllerConfigBase
from hummingbot.strategy_v2.executors.position_executor.data_types import PositionExecutorConfig, TripleBarrierConfig
from hummingbot.strategy_v2.models.executor_actions import CreateExecutorAction, ExecutorAction, StopExecutorAction


class SimpleTradingControllerConfigBase(ControllerConfigBase):
    """
    Simple trading controller configuration with minimal parameters
    """
    controller_type: str = "simple_trading"

    connector_name: str = Field(
        default="binance_perpetual",
        json_schema_extra={
            "prompt": "Enter the connector name (e.g., binance, binance_perpetual): ",
            "prompt_on_new": True
        }
    )

    trading_pair: str = Field(
        default="BTC-USDT",
        json_schema_extra={
            "prompt": "Enter the trading pair (e.g., BTC-USDT): ",
            "prompt_on_new": True
        }
    )

    total_amount_quote: Decimal = Field(
        default=Decimal("100"),
        json_schema_extra={
            "prompt": "Enter the total amount in quote asset to use for trading: ",
            "prompt_on_new": True,
            "is_updatable": True
        }
    )

    order_refresh_time: int = Field(
        default=30,  # 30 seconds
        json_schema_extra={
            "prompt": "Enter order refresh time in seconds (e.g., 300 for 5 minutes): ",
            "prompt_on_new": True,
            "is_updatable": True
        }
    )

    emergency_stop_loss: Optional[Decimal] = Field(
        default=Decimal("0.05"),  # 5% emergency stop
        json_schema_extra={
            "prompt": "Enter emergency stop loss as decimal (e.g., 0.05 for 5%), or leave empty for none: ",
            "prompt_on_new": True,
            "is_updatable": True
        }
    )


class SimpleTradingControllerBase(ControllerBase):
    """
    Simple base controller for basic limit order trading with signals
    """

    def __init__(self, config: SimpleTradingControllerConfigBase, *args, **kwargs):
        super().__init__(config, *args, **kwargs)
        self.config = config

    async def update_processed_data(self):
        """
        Update processed data - to be implemented by child classes
        Child classes should set self.processed_data["signal"] to 1 (buy), -1 (sell), or 0 (neutral)
        """
        # Child classes should implement signal generation here
        pass

    def determine_executor_actions(self) -> List[ExecutorAction]:
        """
        Create executors based on signals from processed data
        """
        actions = []

        # Get signal from processed data (set by child class)
        signal = self.processed_data.get("signal", 0)

        if signal == 0:
            return actions

        # Check if we already have active executors
        active_executors = self.filter_executors(
            executors=self.executors_info,
            filter_func=lambda x: x.is_active and not x.is_done
        )

        # Only create new executor if we don't have active ones
        if len(active_executors) == 0:
            # Determine trade side based on signal
            side = TradeType.BUY if signal > 0 else TradeType.SELL

            price_type = PriceType.BestAsk if side == TradeType.BUY else PriceType.BestBid
            entry_price = self.market_data_provider.get_price_by_type(
                self.config.connector_name,
                self.config.trading_pair,
                price_type
            )

            if entry_price is None or entry_price <= Decimal("0"):
                self.logger().warning(
                    f"Controller {self.config.id} could not fetch a valid entry price for"
                    f" {self.config.connector_name}-{self.config.trading_pair}."
                )
                return actions

            amount_quote = self.config.total_amount_quote
            if amount_quote <= Decimal("0"):
                self.logger().warning(
                    f"Controller {self.config.id} has non-positive total_amount_quote={amount_quote}."
                )
                return actions

            amount_base = amount_quote / entry_price
            connector = self.market_data_provider.get_connector(self.config.connector_name)
            amount_base = connector.quantize_order_amount(self.config.trading_pair, amount_base)

            if amount_base <= Decimal("0"):
                self.logger().warning(
                    f"Controller {self.config.id} computed non-positive base amount after quantization."
                )
                return actions

            # Create position config
            position_config = PositionExecutorConfig(
                timestamp=self.market_data_provider.time(),
                connector_name=self.config.connector_name,
                trading_pair=self.config.trading_pair,
                side=side,
                entry_price=entry_price,
                amount=amount_base,
                triple_barrier_config=self._get_triple_barrier_config()
            )

            actions.append(
                CreateExecutorAction(
                    controller_id=self.config.id,
                    executor_config=position_config
                )
            )

        # Check for executor refresh
        executors_to_refresh = self.filter_executors(
            executors=self.executors_info,
            filter_func=lambda x: (
                x.is_active and
                not x.is_trading and
                self.market_data_provider.time() - x.timestamp > self.config.order_refresh_time
            )
        )

        for executor in executors_to_refresh:
            actions.append(
                StopExecutorAction(
                    controller_id=self.config.id,
                    executor_id=executor.id
                )
            )

        return actions

    def _get_triple_barrier_config(self) -> TripleBarrierConfig:
        """
        Create a simple triple barrier config with only emergency stop loss
        """
        return TripleBarrierConfig(
            stop_loss=self.config.emergency_stop_loss,
            take_profit=None,  # No take profit, exit based on signals
            time_limit=None,  # No time limit
            trailing_stop=None,
            open_order_type=OrderType.LIMIT,
            stop_loss_order_type=OrderType.MARKET,
            take_profit_order_type=OrderType.LIMIT,
            time_limit_order_type=OrderType.MARKET
        )

    def to_format_status(self) -> List[str]:
        """
        Format status for display - can be extended by child classes
        """
        lines = []
        lines.append(f"Controller: {self.config.id}")
        lines.append(f"Trading Pair: {self.config.trading_pair}")
        lines.append(f"Amount: {self.config.total_amount_quote}")

        # Show active executors
        active_executors = self.filter_executors(
            executors=self.executors_info,
            filter_func=lambda x: x.is_active
        )

        if active_executors:
            lines.append(f"Active Executors: {len(active_executors)}")
            for executor in active_executors:
                lines.append(f"  - {executor.id}: {executor.status}")

        return lines
