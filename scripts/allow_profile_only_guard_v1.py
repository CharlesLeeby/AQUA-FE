#!/usr/bin/env python3
"""Explicit non-confirmatory guard bypass for resource/reproduction diagnostics.

This helper must never be used to label an output as a frozen P07 result.  It
exists only so post-freeze source-drift compatibility and resource profiling
can execute while retaining that boundary in their surrounding receipts.
"""

import sys


print("PROFILE_ONLY_GUARD_BYPASS: output is not a frozen confirmatory result")
sys.exit(0)
