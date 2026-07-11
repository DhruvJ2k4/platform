"""Shared pytest configuration: deterministic hypothesis profiles.

Hypothesis does not read HYPOTHESIS_PROFILE itself, so this conftest both registers
the "ci" profile and loads whichever profile the environment selects. CI sets
HYPOTHESIS_PROFILE=ci for derandomized, reproducible property runs (doc 23).
"""

import os

from hypothesis import settings

settings.register_profile("ci", derandomize=True)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))
