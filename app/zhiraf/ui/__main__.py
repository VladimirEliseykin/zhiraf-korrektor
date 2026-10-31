import multiprocessing
import sys

from zhiraf.ui.app import main

# the check runs in a spawned child that re-imports this file: only the real start may call main()
if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
