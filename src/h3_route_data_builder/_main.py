"""Main module for h3_route_data_builder package."""
from .utils import get_logger

# configure module logging, the same logger as the package-level logger
logger = get_logger("h3_route_data_builder", level="DEBUG", add_stream_handler=False)
    