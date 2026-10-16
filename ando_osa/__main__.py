"""``python -m ando_osa [command …]``: a headless command, or the desktop app without one."""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
