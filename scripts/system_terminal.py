"""Real host PTYs, owned and reaped by the System agent."""

import fcntl
import os
import signal
import struct
import subprocess
import sys
import termios
from contextlib import suppress
from pathlib import Path


class HostTerminal:
    def __init__(self, shell, directory):
        import pty

        descriptor, slave = pty.openpty()
        try:
            # No Python preexec/fork child runs inside the agent's threaded process.
            self.process = subprocess.Popen(
                [
                    sys.executable,
                    str(Path(__file__).with_name("system_terminal_child.py")),
                    shell,
                    directory,
                ],
                stdin=slave,
                stdout=slave,
                stderr=slave,
                start_new_session=True,
                close_fds=True,
            )
        except BaseException:
            os.close(descriptor)
            raise
        finally:
            os.close(slave)
        self.pid, self.fd, self.closed = self.process.pid, descriptor, False
        os.set_blocking(descriptor, False)
        self.resize(100, 24)

    def resize(self, cols, rows):
        if not 2 <= cols <= 500 or not 2 <= rows <= 200:
            raise ValueError("Invalid terminal size")
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def close(self):
        if self.closed:
            return
        self.closed = True
        import psutil

        with suppress(psutil.Error):
            for child in psutil.Process(self.pid).children(recursive=True):
                with suppress(psutil.Error):
                    child.kill()
        # The PTY foreground group can differ from the shell group (job control).
        groups = {self.pid}
        with suppress(OSError):
            groups.add(os.tcgetpgrp(self.fd))
        for group in groups:
            if group > 0 and group != os.getpgrp():
                with suppress(ProcessLookupError, PermissionError):
                    os.killpg(group, signal.SIGKILL)
        with suppress(OSError):
            os.close(self.fd)
        with suppress(ChildProcessError):
            self.process.wait()
