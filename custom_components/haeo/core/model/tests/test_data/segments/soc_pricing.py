"""SOC pricing segment scenarios."""

from typing import Any

from highspy import Highs
from highspy.highs import HighspyArray
import numpy as np
from numpy.typing import NDArray

from custom_components.haeo.core.model.element import Element
from custom_components.haeo.core.model.elements.segments import SocPricingSegment

from ..segment_types import SegmentErrorScenario, SegmentScenario


class MockBattery(Element[str]):
    """Minimal battery element for SOC pricing scenarios."""

    stored_energy: HighspyArray

    def __init__(
        self,
        name: str,
        periods: NDArray[np.floating[Any]],
        solver: Highs,
        stored_energy: HighspyArray,
    ) -> None:
        """Initialize the mock battery."""
        super().__init__(name=name, periods=periods, solver=solver, output_names=frozenset())
        self.stored_energy = stored_energy


class DummyElement(Element[str]):
    """Minimal non-battery element for segment endpoints."""

    def __init__(self, name: str, periods: NDArray[np.floating[Any]], solver: Highs) -> None:
        """Initialize the dummy element."""
        super().__init__(name=name, periods=periods, solver=solver, output_names=frozenset())


def _battery_endpoints_fixed(solver: Highs, periods: NDArray[np.floating[Any]]) -> tuple[Element[Any], Element[Any]]:
    stored_energy = solver.addVariables(len(periods) + 1, lb=0, name_prefix="battery_e_", out_array=True)
    solver.addConstr(stored_energy[0] == 5.0)
    solver.addConstr(stored_energy[1] == 2.0)
    solver.addConstr(stored_energy[2] == 9.0)
    battery = MockBattery("battery", periods, solver, stored_energy)
    target = DummyElement("target", periods, solver)
    return battery, target


def _battery_endpoints_free(solver: Highs, periods: NDArray[np.floating[Any]]) -> tuple[Element[Any], Element[Any]]:
    stored_energy = solver.addVariables(len(periods) + 1, lb=0, name_prefix="battery_e_", out_array=True)
    battery = MockBattery("battery", periods, solver, stored_energy)
    target = DummyElement("target", periods, solver)
    return battery, target


def _battery_endpoints_recovers_past_start(
    solver: Highs, periods: NDArray[np.floating[Any]]
) -> tuple[Element[Any], Element[Any]]:
    """Already 2 kWh below threshold at t=0, stays there, then recovers well past it.

    Regression for a formulation that priced the raw slack delta directly: since the
    pre-horizon depth was never actually paid for during this optimization, recovering
    past it must not manufacture a rebate — the cost must floor at 0, not go negative
    (which previously made the LP unbounded, since the slack driving that rebate had no
    upper bound).
    """
    stored_energy = solver.addVariables(len(periods) + 1, lb=0, name_prefix="battery_e_", out_array=True)
    solver.addConstr(stored_energy[0] == 1.0)
    solver.addConstr(stored_energy[1] == 1.0)
    solver.addConstr(stored_energy[2] == 5.0)
    battery = MockBattery("battery", periods, solver, stored_energy)
    target = DummyElement("target", periods, solver)
    return battery, target


SCENARIOS: list[SegmentScenario] = [
    {
        "description": "SOC pricing applies costs outside thresholds",
        "factory": SocPricingSegment,
        "spec": {
            "segment_type": "soc_pricing",
            "discharge_energy_threshold": np.array([3.0, 3.0]),
            "charge_capacity_threshold": np.array([8.0, 8.0]),
            "discharge_energy_price": np.array([0.5, 0.5]),
            "charge_capacity_price": np.array([0.2, 0.2]),
        },
        "periods": np.array([1.0, 0.5]),
        "inputs": {"minimize_cost": True},
        "expected_outputs": {
            "discharge_energy_slack": (1.0, 0.0),
            "charge_capacity_slack": (0.0, 1.0),
            # Delta-based pricing: discharge nets to 0 (entry 0.5 in period 0, exit -0.5 in
            # period 1); charge only enters in period 1 (0.2), never exits within the horizon.
            "objective_value": 0.2,
        },
        "endpoint_factory": _battery_endpoints_fixed,
    },
    {
        "description": "SOC pricing supports discharge-only penalty",
        "factory": SocPricingSegment,
        "spec": {
            "segment_type": "soc_pricing",
            "discharge_energy_threshold": np.array([3.0, 3.0]),
            "discharge_energy_price": np.array([0.5, 0.5]),
        },
        "periods": np.array([1.0, 0.5]),
        "inputs": {"minimize_cost": True},
        # Delta-based pricing: enters the buffer in period 0 (+0.5) and fully exits in
        # period 1 (-0.5), netting to 0 since it never ends the horizon still in the buffer.
        "expected_outputs": {"discharge_energy_slack": (1.0, 0.0), "objective_value": 0.0},
        "endpoint_factory": _battery_endpoints_fixed,
    },
    {
        "description": "SOC pricing supports charge-only penalty",
        "factory": SocPricingSegment,
        "spec": {
            "segment_type": "soc_pricing",
            "charge_capacity_threshold": np.array([8.0, 8.0]),
            "charge_capacity_price": np.array([0.2, 0.2]),
        },
        "periods": np.array([1.0, 0.5]),
        "inputs": {"minimize_cost": True},
        # Delta-based pricing: no charge-capacity slack until period 1, where it enters the
        # buffer (+0.2) and the horizon ends there, so the cost is not yet rebated.
        "expected_outputs": {"charge_capacity_slack": (0.0, 1.0), "objective_value": 0.2},
        "endpoint_factory": _battery_endpoints_fixed,
    },
    {
        "description": "SOC pricing floors the rebate instead of going negative",
        "factory": SocPricingSegment,
        "spec": {
            "segment_type": "soc_pricing",
            "discharge_energy_threshold": np.array([3.0, 3.0]),
            "discharge_energy_price": np.array([0.5, 0.5]),
        },
        "periods": np.array([1.0, 1.0]),
        "inputs": {"minimize_cost": True},
        "expected_outputs": {"discharge_energy_slack": (2.0, 0.0), "objective_value": 0.0},
        "endpoint_factory": _battery_endpoints_recovers_past_start,
    },
    {
        "description": "SOC pricing passes through power",
        "factory": SocPricingSegment,
        "spec": {"segment_type": "soc_pricing"},
        "periods": np.array([1.0, 0.5]),
        "inputs": {"power_in": (3.0, 4.0)},
        "expected_outputs": {
            "power_in": (3.0, 4.0),
            "power_out": (3.0, 4.0),
        },
        "endpoint_factory": _battery_endpoints_free,
    },
]


ERROR_SCENARIOS: list[SegmentErrorScenario] = [
    {
        "description": "SOC pricing requires a battery endpoint",
        "factory": SocPricingSegment,
        "spec": {"segment_type": "soc_pricing"},
        "periods": np.array([1.0]),
        "error": TypeError,
        "match": "SOC pricing segment requires a battery element endpoint",
    },
    {
        "description": "SOC pricing requires discharge threshold with price",
        "factory": SocPricingSegment,
        "spec": {"segment_type": "soc_pricing", "discharge_energy_price": np.array([0.1])},
        "periods": np.array([1.0]),
        "error": ValueError,
        "match": "discharge_energy_threshold is required when discharge_energy_price is set",
        "endpoint_factory": _battery_endpoints_free,
    },
    {
        "description": "SOC pricing requires charge threshold with price",
        "factory": SocPricingSegment,
        "spec": {"segment_type": "soc_pricing", "charge_capacity_price": np.array([0.1])},
        "periods": np.array([1.0]),
        "error": ValueError,
        "match": "charge_capacity_threshold is required when charge_capacity_price is set",
        "endpoint_factory": _battery_endpoints_free,
    },
]


__all__ = ["ERROR_SCENARIOS", "SCENARIOS"]
