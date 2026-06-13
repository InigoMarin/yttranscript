"""Allow `python -m yttranscript` invocation."""

import sys

from .cli import main

if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        sys.exit(e.code if isinstance(e.code, int) else 1)
    sys.exit(0)
