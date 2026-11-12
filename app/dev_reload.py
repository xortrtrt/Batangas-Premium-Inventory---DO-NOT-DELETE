"""Development-only browser refresh state."""

import os
import time


ENABLED = os.environ.get("DEV_LIVE_RELOAD") == "1"
VERSION = str(time.time_ns())
