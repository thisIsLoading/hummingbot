"""
Exception classes for Loading Order Flow V1 Controller
"""


class CVDControllerError(Exception):
    """Base exception for CVD controller errors"""
    pass


class InvalidTradeDataError(CVDControllerError):
    """Raised when trade data is invalid or corrupted"""
    pass


class ConfigurationError(CVDControllerError):
    """Raised when configuration is invalid"""
    pass
