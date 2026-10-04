"""Moved to the engine (spellcheck.guards): one copy for evaluation and for the program."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
from spellcheck.guards import *  # noqa: E402,F401,F403
