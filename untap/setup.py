"""Install Chromium using the same Python environment as Untap."""

import argparse
import subprocess
import sys
from typing import Optional, Sequence


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    return subprocess.call([sys.executable, "-m", "playwright", "install", "chromium"])


if __name__ == "__main__":
    raise SystemExit(main())
