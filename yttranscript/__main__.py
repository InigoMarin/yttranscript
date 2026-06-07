"""Allow `python -m yttranscript` invocation."""

import sys

from .cli import main

if __name__ == "__main__":
    main()
    sys.exit(0)
