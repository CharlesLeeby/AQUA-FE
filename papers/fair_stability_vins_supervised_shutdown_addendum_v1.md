# Fair-stability VINS supervised-shutdown addendum v1

Status: **PROSPECTIVE; FROZEN BEFORE THE FIRST NEW VINS REPLAY**  
Parent: `fair_stability_positive_roster_protocol_v1.md`.

The selected VINS-Fusion ROS node calls persistent `ros::spin()` and owns a
persistent synchronization thread.  End of a finite rosbag therefore does not
produce a natural estimator exit.  Requiring natural return code zero would
make every otherwise valid VINS cell fail for a lifecycle property unrelated
to tracking stability.

For the two VINS arms only, `clean supervised exit` means:

1. `rosbag play` reaches its natural return code zero;
2. the VINS child is still alive after the frozen post-bag flush interval;
3. the expected VINS trajectory exists and is nonempty;
4. the supervisor sends exactly one SIGTERM to that exact recorded VINS PID;
5. `wait` returns the expected signal status 143 and confirms child reap;
6. roscore is then terminated and reaped; and
7. no VINS/roscore/rosmaster/rosbag descendant remains.

The expected bag-end SIGTERM is not an algorithm failure, reset, crash, or
retry.  Any VINS exit before the bag-end checkpoint, rosbag nonzero exit,
unexpected signal/status, failed reap, forced SIGKILL, or surviving descendant
is an execution failure.  HFNet remains subject to natural clean exit; this
addendum does not relax its lifecycle gate.

The child lifecycle receipt records PIDs, rosbag return code, bag-end liveness,
sent signal, VINS wait status, roscore wait status, and output existence.  It
is evaluated together with trajectory coverage, initialization, reset/reboot,
and solver-risk checks from the parent protocol.
