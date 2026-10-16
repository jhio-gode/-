"""Keep the optional desktop smoke suite headless on CI/Linux.

Windows users can run the same tests with the normal Qt platform plugin.
"""
from __future__ import annotations

import os


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
