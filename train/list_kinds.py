"""Print gold edits of the given kinds (coverage.kind) with their sentences.

Usage: python list_kinds.py <kind>...
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coverage  # noqa: E402

bench = coverage.bench


def main():
    kinds = set(sys.argv[1:])
    sets = bench.load_sets()
    for item in sets["dev"] + sets["test"]:
        for e in bench.edits(item["src"], item["gold"]):
            k = coverage.kind(e)
            if k in kinds:
                print("%-18s %s → %s | %s" % (k, " ".join(e[3]), " ".join(e[2]), item["src"][:150]))


if __name__ == "__main__":
    main()
