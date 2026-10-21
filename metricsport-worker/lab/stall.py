"""Stop one thread of a process (e.g. tor's main thread, whose TID is its PID)
for N seconds with ptrace, leaving its other threads running.

Usage: python3 stall.py <tid> <seconds>
"""
import ctypes, os, sys, time

libc = ctypes.CDLL(None, use_errno=True)
libc.ptrace.argtypes = [ctypes.c_long] * 2 + [ctypes.c_void_p] * 2
PTRACE_DETACH, PTRACE_SEIZE, PTRACE_INTERRUPT = 17, 0x4206, 0x4207

tid, secs = int(sys.argv[1]), float(sys.argv[2])
if libc.ptrace(PTRACE_SEIZE, tid, None, None) != 0:
    sys.exit("PTRACE_SEIZE failed: errno %d" % ctypes.get_errno())
libc.ptrace(PTRACE_INTERRUPT, tid, None, None)
os.waitpid(tid, 0x40000000)  # __WALL: tid may be a thread
time.sleep(secs)
libc.ptrace(PTRACE_DETACH, tid, None, None)
