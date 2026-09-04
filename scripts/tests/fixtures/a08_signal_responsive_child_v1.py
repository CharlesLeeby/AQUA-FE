#!/usr/bin/python3.8
"""Non-ROS probe child: record inherited mask and exit on TERM."""

import json
import os
from pathlib import Path
import signal
import sys
import time


target = Path(sys.argv[1])
blocked = sorted(
    int(value) for value in signal.pthread_sigmask(signal.SIG_BLOCK, set())
)
running = True


def stop(_signum, _frame):
    global running
    running = False


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
descriptor = os.open(
    str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
    0o444,
)
try:
    os.write(descriptor, (json.dumps({"pid": os.getpid(), "blocked": blocked}) + "\n").encode())
    os.fsync(descriptor)
finally:
    os.close(descriptor)
while running:
    time.sleep(0.02)
