"""citibike2strava — turn Citi Bike email receipts into Strava rides.

Public surface for embedding the core in other front-ends (hosted service,
browser-extension backend, etc.):

    from citibike2strava import parse_receipt, build_gpx, Pipeline, Ride
"""

from .eml import EmlParseError, html_from_eml
from .gpx import build_gpx
from .models import Ride, TrackPoint
from .pipeline import Pipeline, RideResult
from .processed import ProcessedStore
from .receipt import ReceiptParseError, parse_receipt

__version__ = "0.2.0"

__all__ = [
    "parse_receipt",
    "ReceiptParseError",
    "build_gpx",
    "Pipeline",
    "RideResult",
    "Ride",
    "TrackPoint",
    "html_from_eml",
    "EmlParseError",
    "ProcessedStore",
    "__version__",
]
