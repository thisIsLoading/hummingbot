"""
Trade validation components for market data processing
"""
from decimal import Decimal, InvalidOperation
from typing import Any, Tuple

from controllers.directional_trading.loading_order_flow_v1_components.exceptions import InvalidTradeDataError


class TradeValidator:
    """Validates and normalizes trade data from market events"""

    @staticmethod
    def validate_price(price: Any) -> Decimal:
        """
        Validate and convert price to Decimal

        Args:
            price: Raw price value from trade event

        Returns:
            Validated price as Decimal

        Raises:
            InvalidTradeDataError: If price is invalid
        """
        try:
            price_decimal = Decimal(str(price))

            if price_decimal <= 0:
                raise InvalidTradeDataError(f"Price must be positive: {price}")

            if price_decimal.is_nan():
                raise InvalidTradeDataError(f"Price is NaN: {price}")

            if price_decimal.is_infinite():
                raise InvalidTradeDataError(f"Price is infinite: {price}")

            return price_decimal

        except (InvalidOperation, ValueError) as e:
            raise InvalidTradeDataError(f"Cannot convert price to Decimal: {e}")

    @staticmethod
    def validate_volume(volume: Any) -> Decimal:
        """
        Validate and convert volume to Decimal

        Args:
            volume: Raw volume value from trade event

        Returns:
            Validated volume as Decimal

        Raises:
            InvalidTradeDataError: If volume is invalid
        """
        try:
            volume_decimal = Decimal(str(volume))

            if volume_decimal < 0:
                raise InvalidTradeDataError(f"Volume cannot be negative: {volume}")

            if volume_decimal.is_nan():
                raise InvalidTradeDataError(f"Volume is NaN: {volume}")

            if volume_decimal.is_infinite():
                raise InvalidTradeDataError(f"Volume is infinite: {volume}")

            return volume_decimal

        except (InvalidOperation, ValueError) as e:
            raise InvalidTradeDataError(f"Cannot convert volume to Decimal: {e}")

    @staticmethod
    def validate_timestamp(timestamp: Any) -> float:
        """
        Validate timestamp

        Args:
            timestamp: Raw timestamp from trade event

        Returns:
            Validated timestamp as float

        Raises:
            InvalidTradeDataError: If timestamp is invalid
        """
        try:
            timestamp_float = float(timestamp)

            if timestamp_float < 0:
                raise InvalidTradeDataError(f"Timestamp cannot be negative: {timestamp}")

            return timestamp_float

        except (TypeError, ValueError) as e:
            raise InvalidTradeDataError(f"Cannot convert timestamp to float: {e}")

    def validate_trade(self, price: Any, volume: Any, timestamp: Any) -> Tuple[Decimal, Decimal, float]:
        """
        Validate complete trade data

        Args:
            price: Raw price value
            volume: Raw volume value
            timestamp: Raw timestamp value

        Returns:
            Tuple of (validated_price, validated_volume, validated_timestamp)

        Raises:
            InvalidTradeDataError: If any trade data is invalid
        """
        validated_price = self.validate_price(price)
        validated_volume = self.validate_volume(volume)
        validated_timestamp = self.validate_timestamp(timestamp)

        return validated_price, validated_volume, validated_timestamp
