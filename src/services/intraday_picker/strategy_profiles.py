"""Strategy-profile definitions.

Profiles describe distinct trade setups. Do not collapse strong-start,
pullback and reversal semantics into one score.
"""

from __future__ import annotations

PROFILES: dict[str, dict[str, tuple[str, ...]]] = {
    "strong_start": {
        "alphasift": ("capital_heat", "volume_breakout"),
        "confirmations": ("reversal_breakout",),
        "quality_reference": ("balanced_alpha",),
    },
    "pullback": {
        "alphasift": ("shrink_pullback",),
        "confirmations": ("buy_pullback",),
        "quality_reference": ("balanced_alpha",),
    },
    "reversal": {
        "alphasift": ("oversold_reversal",),
        "confirmations": ("bottom_reversal",),
        "quality_reference": ("balanced_alpha",),
    },
}


def get_profile(profile: str) -> dict[str, tuple[str, ...]]:
    return PROFILES.get(profile, PROFILES["strong_start"])
