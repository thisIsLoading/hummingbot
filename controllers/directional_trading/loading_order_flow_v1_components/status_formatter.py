"""
Status display formatter for CVD Range Bar Controller
"""
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple


class StatusFormatter:
    """Formats controller status for terminal display with dynamic box sizing"""

    def __init__(self, min_width: int = 40):
        """
        Initialize formatter

        Args:
            min_width: Minimum box width
        """
        self.min_width = min_width

    def format_status(self, config: Any, status_data: Dict[str, Any]) -> List[str]:
        """
        Format status data into boxed display

        Args:
            config: Controller configuration
            status_data: Status data from MarketDataManager

        Returns:
            List of formatted display lines
        """
        # Build content lines first to determine max width
        content_lines = []

        # Header
        content_lines.append(("header", f" Pair: {config.trading_pair} | Range: {config.range_size} "))

        # Current bar
        if status_data.get("current_bar"):
            content_lines.extend(self._format_current_bar(status_data["current_bar"], config.range_size))

        # Last completed bar
        if status_data.get("last_completed_bar_info"):
            content_lines.extend(self._format_completed_bar(status_data["last_completed_bar_info"]))

        # POC and confluence
        if status_data.get("current_poc") or status_data.get("poc_confluence"):
            content_lines.extend(self._format_poc_data(status_data))

        # Statistics
        content_lines.extend(self._format_statistics(status_data))

        # Build the box
        return self._build_box(content_lines)

    def _format_current_bar(self, bar: Dict[str, Any], range_size: Decimal) -> List[Tuple[str, str]]:
        """Format current bar information"""
        lines = [
            ("divider", None),
            ("content", " Current Bar:"),
            ("content", f"         Range: [{bar['range_low']:.2f} - {bar['range_high']:.2f}]"),
            ("content", f"         Price: {bar['price']:.2f}"),
            ("content", f"           CVD: {bar['cvd']:.4f}"),
            ("content", f"    Range Used: {bar['range_used']:.2f}/{range_size:.2f} ({bar['range_pct']:.1f}%)"),
            ("content", f"        Volume: {bar['volume']:.4f}"),
            ("content", f"        Trades: {bar['trade_count']}"),
        ]
        return lines

    def _format_completed_bar(self, info: str) -> List[Tuple[str, str]]:
        """Format completed bar information"""
        lines = [("divider", None)]

        # Parse the completed bar info string
        # Format: "[COMPLETED] Price: X->Y | CVD: A->B | Vol: V | Trades: T | POC: P | Duration: D"
        if "[COMPLETED]" in info:
            info = info.replace("[COMPLETED]", "").strip()

        lines.append(("content", " Last Completed Bar:"))

        # Split by pipe and format each metric
        parts = info.split(" | ")
        for part in parts:
            if ":" in part:
                key, value = part.split(":", 1)
                key = key.strip()
                value = value.strip()

                # Right-align the key names like current bar
                if key == "Price":
                    lines.append(("content", f"         Price: {value}"))
                elif key == "CVD":
                    lines.append(("content", f"           CVD: {value}"))
                elif key == "Vol":
                    lines.append(("content", f"        Volume: {value}"))
                elif key == "Trades":
                    lines.append(("content", f"        Trades: {value}"))
                elif key == "POC":
                    lines.append(("content", f"           POC: {value}"))
                elif key == "Duration":
                    lines.append(("content", f"      Duration: {value}"))

        return lines

    def _format_poc_data(self, status_data: Dict[str, Any]) -> List[Tuple[str, str]]:
        """Format POC and confluence data"""
        lines = [("divider", None)]

        if status_data.get("current_poc"):
            poc = status_data["current_poc"]
            lines.append(("content", f"           POC: {poc['price']:.2f} (Volume: {poc['volume']:.4f})"))

        if status_data.get("poc_confluence"):
            confluence_str = "    Confluence: "
            for level in status_data["poc_confluence"][:2]:
                confluence_str += f"{level['price']:.2f} ({level['count']}x) "
            lines.append(("content", confluence_str))

        return lines

    def _format_statistics(self, status_data: Dict[str, Any]) -> List[Tuple[str, str]]:
        """Format statistics section"""
        lines = [
            ("divider", None),
            ("content", " Statistics:"),
            ("content", f"  Completed Bars: {status_data['completed_bars']}"),
            ("content", f"    Total Volume: {status_data['total_volume']:.2f}"),
            ("content", f"    Total Trades: {status_data['total_trades']}"),
        ]

        if status_data.get("errors_count", 0) > 0:
            lines.append(("content", f"         Errors: {status_data['errors_count']}"))

        return lines

    def _build_box(self, content_lines: List[Tuple[str, Optional[str]]]) -> List[str]:
        """Build the box with consistent width"""
        # Find max width
        max_width = max(len(line) for type_, line in content_lines if line is not None)
        box_width = max(max_width + 3, self.min_width)  # +3 for borders and right padding

        lines = []

        # Top border
        lines.append("╔" + "═" * (box_width - 2) + "╗")

        # Content
        for type_, content in content_lines:
            if type_ == "header":
                # Header gets centered
                lines.append(f"║{content:^{box_width - 2}}║")
            elif type_ == "divider":
                lines.append("╟" + "─" * (box_width - 2) + "╢")
            elif type_ == "content":
                # Content gets left-aligned with 1 space right padding
                lines.append(f"║{content:<{box_width - 3}} ║")

        # Bottom border
        lines.append("╚" + "═" * (box_width - 2) + "╝")

        return lines
