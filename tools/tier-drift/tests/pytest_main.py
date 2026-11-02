import sys

import pytest


def main() -> int:
    # A py_test's runfiles hold only its own srcs, so "tests" collects exactly
    # the test modules BUILD.bazel lists for that target.
    return pytest.main(["tests", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
