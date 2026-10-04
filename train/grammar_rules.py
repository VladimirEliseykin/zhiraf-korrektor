"""Moved to the engine (spellcheck.grammar_rules): one copy for evaluation and for the program."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
from spellcheck.grammar_rules import *  # noqa: E402,F401,F403
from spellcheck.grammar_rules import morph  # noqa: E402,F401
