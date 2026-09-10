"""SOC-based pricing segment — penalizes operation outside SOC thresholds."""

from typing import Any, Literal, NotRequired

from highspy import Highs
from highspy.highs import HighspyArray, highs_linear_expression
import numpy as np
from numpy.typing import NDArray
from typing_extensions import TypedDict

from custom_components.haeo.core.model.element import Element
from custom_components.haeo.core.model.reactive import TrackedParam, constraint, cost
from custom_components.haeo.core.model.util import broadcast_to_sequence

from .segment import Segment


class SocPricingSegmentSpec(TypedDict):
    """Specification for creating a SocPricingSegment."""

    segment_type: Literal["soc_pricing"]
    discharge_energy_threshold: NotRequired[NDArray[np.floating[Any]] | float | None]
    charge_capacity_threshold: NotRequired[NDArray[np.floating[Any]] | float | None]
    discharge_energy_price: NotRequired[NDArray[np.floating[Any]] | float | None]
    charge_capacity_price: NotRequired[NDArray[np.floating[Any]] | float | None]


def _exposed_slack(
    threshold: NDArray[np.float64] | None,
    price: NDArray[np.float64] | None,
    slack: HighspyArray,
) -> HighspyArray | None:
    return slack if threshold is not None and price is not None else None


class SocPricingSegment(Segment):
    """Penalizes battery operation outside SOC thresholds using slack variables."""

    discharge_energy_threshold: TrackedParam[NDArray[np.float64] | None] = TrackedParam()
    charge_capacity_threshold: TrackedParam[NDArray[np.float64] | None] = TrackedParam()
    discharge_energy_price: TrackedParam[NDArray[np.float64] | None] = TrackedParam()
    charge_capacity_price: TrackedParam[NDArray[np.float64] | None] = TrackedParam()

    def __init__(
        self,
        segment_id: str,
        n_periods: int,
        periods: NDArray[np.floating[Any]],
        solver: Highs,
        *,
        spec: SocPricingSegmentSpec,
        source_element: Element[Any],
        target_element: Element[Any],
        power_in: dict[int, HighspyArray],
    ) -> None:
        """Initialize SOC pricing segment."""
        super().__init__(
            segment_id,
            n_periods,
            periods,
            solver,
            source_element=source_element,
            target_element=target_element,
            power_in=power_in,
        )
        self._battery = self._get_battery()

        self.discharge_energy_threshold = broadcast_to_sequence(spec.get("discharge_energy_threshold"), n_periods)
        self.charge_capacity_threshold = broadcast_to_sequence(spec.get("charge_capacity_threshold"), n_periods)
        self.discharge_energy_price = broadcast_to_sequence(spec.get("discharge_energy_price"), n_periods)
        self.charge_capacity_price = broadcast_to_sequence(spec.get("charge_capacity_price"), n_periods)

        if self.discharge_energy_price is not None and self.discharge_energy_threshold is None:
            msg = "discharge_energy_threshold is required when discharge_energy_price is set"
            raise ValueError(msg)
        if self.charge_capacity_price is not None and self.charge_capacity_threshold is None:
            msg = "charge_capacity_threshold is required when charge_capacity_price is set"
            raise ValueError(msg)

        # Slack arrays include one extra entry (index 0) for the depth already present at the
        # start of the horizon, so the cost below can be computed as a delta between
        # consecutive periods without a special case for the first period.
        self._discharge_energy_slack = solver.addVariables(
            n_periods + 1,
            lb=0,
            name_prefix=f"{segment_id}_discharge_energy_",
            out_array=True,
        )
        self._charge_capacity_slack = solver.addVariables(
            n_periods + 1,
            lb=0,
            name_prefix=f"{segment_id}_charge_capacity_",
            out_array=True,
        )

        # Outstanding toll owed for the current excursion: paid[0] is pinned to 0, and
        # paid[t] is only ever bounded below by max(0, paid[t-1] + price * delta_slack(t)).
        # The floor at 0 caps any rebate at what was actually paid in — without it, slack
        # would be free to grow without bound to manufacture unlimited rebate (see
        # soc_pricing_cost for why only the final value is priced).
        self._discharge_energy_paid = solver.addVariables(
            n_periods + 1,
            lb=0,
            name_prefix=f"{segment_id}_discharge_paid_",
            out_array=True,
        )
        self._charge_capacity_paid = solver.addVariables(
            n_periods + 1,
            lb=0,
            name_prefix=f"{segment_id}_charge_paid_",
            out_array=True,
        )

    def _get_battery(self) -> Any:
        """Find the battery element from the connection endpoints."""
        for element in (self.source_element, self.target_element):
            if hasattr(element, "stored_energy"):
                return element
        msg = "SOC pricing segment requires a battery element endpoint"
        raise TypeError(msg)

    @property
    def discharge_energy_slack(self) -> HighspyArray | None:
        """Slack for energy below discharge threshold (excludes the pre-horizon boundary)."""
        return _exposed_slack(
            self.discharge_energy_threshold,
            self.discharge_energy_price,
            self._discharge_energy_slack[1:],
        )

    @property
    def charge_capacity_slack(self) -> HighspyArray | None:
        """Slack for energy above charge capacity threshold (excludes the pre-horizon boundary)."""
        return _exposed_slack(
            self.charge_capacity_threshold,
            self.charge_capacity_price,
            self._charge_capacity_slack[1:],
        )

    @constraint
    def soc_slack_bounds(self) -> list[highs_linear_expression] | None:
        """Bound slack variables to SOC threshold violations when penalties apply.

        Index 0 tracks the depth already present at the start of the horizon (using the
        first period's threshold as the reference), so ``soc_pricing_cost`` can price the
        change in depth period over period without a special case for the first period.
        """
        bounds: list[highs_linear_expression] = []
        stored = np.asarray(self._battery.stored_energy, dtype=object)

        if self.discharge_energy_threshold is not None and self.discharge_energy_price is not None:
            threshold = self.discharge_energy_threshold
            bounds.extend(list(self._discharge_energy_slack[0:1] >= threshold[0] - stored[0:1]))
            bounds.extend(list(self._discharge_energy_slack[1:] >= threshold - stored[1:]))

        if self.charge_capacity_threshold is not None and self.charge_capacity_price is not None:
            threshold = self.charge_capacity_threshold
            bounds.extend(list(self._charge_capacity_slack[0:1] >= stored[0:1] - threshold[0]))
            bounds.extend(list(self._charge_capacity_slack[1:] >= stored[1:] - threshold))

        return bounds or None

    @constraint
    def soc_paid_bounds(self) -> list[highs_linear_expression] | None:
        """Bound the outstanding toll to a floored running total of priced slack changes.

        ``paid[t] >= paid[t-1] + price(t) * (slack(t) - slack(t-1))`` together with
        ``paid[t] >= 0`` implements ``paid[t] = max(0, ...)`` once ``soc_pricing_cost``
        minimizes ``paid[-1]``: deepening the excursion raises the toll, recovering from
        it lowers it, and the floor stops a recovery from ever earning more rebate than
        was actually paid in. Index 0 is the base case of the same relation, treating the
        implicit ``slack[-1]`` and ``paid[-1]`` before the horizon as zero — so it is not
        pinned to zero itself: a real pre-existing excursion (``slack[0] > 0``) already
        owes ``price(0) * slack[0]`` before the horizon even starts.

        This also keeps every ``slack(t)`` pinned to its true minimal (data-driven) value:
        minimizing ``paid[-1]`` transitively wants every earlier ``paid(t)`` — and hence
        every ``slack(t)``, via its strictly positive price coefficient at each step —
        as small as feasible. Without this, a slack could float to an arbitrary degenerate
        value (many alternate paths net to the same final toll) which would make the
        exposed per-period slack outputs meaningless, or worse: were ``paid[0]`` pinned to
        exactly 0 instead of bounded by ``price(0) * slack[0]``, ``slack[0]`` would have no
        upper bound and no cost, letting it be inflated to manufacture unlimited rebate on a
        real violation later in the horizon.
        """
        bounds: list[highs_linear_expression] = []

        if self.discharge_energy_price is not None and self.discharge_energy_threshold is not None:
            slack, paid, price = self._discharge_energy_slack, self._discharge_energy_paid, self.discharge_energy_price
            bounds.extend(list(paid[0:1] >= price[0:1] * slack[0:1]))
            bounds.extend(list(paid[1:] >= paid[:-1] + (slack[1:] - slack[:-1]) * price))

        if self.charge_capacity_price is not None and self.charge_capacity_threshold is not None:
            slack, paid, price = self._charge_capacity_slack, self._charge_capacity_paid, self.charge_capacity_price
            bounds.extend(list(paid[0:1] >= price[0:1] * slack[0:1]))
            bounds.extend(list(paid[1:] >= paid[:-1] + (slack[1:] - slack[:-1]) * price))

        return bounds or None

    @cost
    def soc_pricing_cost(self) -> highs_linear_expression | None:
        """Penalty cost for moving deeper outside SOC thresholds, rebated for moving back.

        Only the final outstanding toll (see ``soc_paid_bounds``) is priced: minimizing it
        drives the whole chain down to the tightest feasible value at each step, which is
        exactly the floored running total of period-over-period slack changes at each
        period's own price. A buffer excursion that fully recovers before the horizon ends
        nets to zero cost regardless of how many periods it spanned — not summed per period
        held — while an excursion still open at the end keeps its unrebated toll.
        """
        cost_terms = []
        if self.discharge_energy_price is not None and self.discharge_energy_threshold is not None:
            cost_terms.append(Highs.qsum(self._discharge_energy_paid[-1:]))
        if self.charge_capacity_price is not None and self.charge_capacity_threshold is not None:
            cost_terms.append(Highs.qsum(self._charge_capacity_paid[-1:]))
        if not cost_terms:
            return None
        if len(cost_terms) == 1:
            return cost_terms[0]
        return Highs.qsum(cost_terms)


__all__ = ["SocPricingSegment", "SocPricingSegmentSpec"]
