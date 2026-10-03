"""Acquire the new session's controlling terminal, then replace this process with the shell."""

import fcntl
import os
import sys
import termios


def main():
    shell, directory = sys.argv[1:]
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    os.chdir(directory)
    os.execve(
        shell, [shell, "-l"], {**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor"}
    )


if __name__ == "__main__":
    main()
