"""
Metrics collection and tracking components
"""
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict


class MetricsCollector:
    """Collects and tracks performance metrics"""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.metrics: Dict[str, Any] = {
            "trades_processed": 0,
            "bars_completed": 0,
            "errors_count": 0,
            "last_update": None,
            "processing_times": deque(maxlen=100)
        }

    def record_trade(self):
        """Record a processed trade"""
        if self.enabled:
            self.metrics["trades_processed"] += 1
            self.metrics["last_update"] = datetime.now(timezone.utc)

    def record_bar_completion(self):
        """Record a completed bar"""
        if self.enabled:
            self.metrics["bars_completed"] += 1

    def record_error(self):
        """Record an error occurrence"""
        if self.enabled:
            self.metrics["errors_count"] += 1

    def record_event(self, event_name: str):
        """Record a named event"""
        if self.enabled:
            if "events" not in self.metrics:
                self.metrics["events"] = {}
            self.metrics["events"][event_name] = self.metrics["events"].get(event_name, 0) + 1
            self.metrics["last_update"] = datetime.now(timezone.utc)

    def get_summary(self) -> Dict[str, Any]:
        """Get metrics summary"""
        return self.metrics.copy() if self.enabled else {}
