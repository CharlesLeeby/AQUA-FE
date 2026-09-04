#!/usr/bin/env python3
"""Non-ROS probe child that deliberately masks SIGINT and SIGTERM."""

import signal
import time


signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})
while True:
    time.sleep(3600)
