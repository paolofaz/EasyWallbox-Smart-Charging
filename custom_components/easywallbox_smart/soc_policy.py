"""Pure SOC-target evaluation used by the future read-only simulator.

No wallbox or Home Assistant service calls. A pause *candidate* is not an
authorization to use the charge-pause switch.
"""

from math import isfinite
from numbers import Real
from typing import NamedTuple


class TargetStatus(NamedTuple):
    """SOC assessment, independent of the wallbox's actual electric state."""

    target_reached: bool | None
    pause_candidate: bool
    reason: str


def assess_target(
    soc: float | None,
    target: int,
    *,
    is_fresh_and_valid: bool,
) -> TargetStatus:
    """Never propose a SOC-based charge pause for the 100% target.

    With 100% target, energy/duration forecasts may still use that target.
    The car can finish its battery management/balancing without this logic
    intervening. A future controller must *also* check the session mode,
    manual pauses, current wallbox state and confirmed charging status.
    """
    if isinstance(target, bool) or not isinstance(target, int) or not 1 <= target <= 100:
        raise ValueError("target must be an integer in the range 1..100")
    if (
        not is_fresh_and_valid
        or soc is None
        or isinstance(soc, bool)
        or not isinstance(soc, Real)
        or not isfinite(soc)
        or not 0 <= soc <= 100
    ):
        return TargetStatus(None, False, "soc_unreliable")
    reached = soc >= target
    if target == 100:
        return TargetStatus(reached, False, "full_charge_managed_by_vehicle")
    if reached:
        return TargetStatus(True, True, "sub_100_target_reached")
    return TargetStatus(False, False, "target_pending")
