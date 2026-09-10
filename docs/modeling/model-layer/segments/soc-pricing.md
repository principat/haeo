# SOC pricing segment

The `SocPricingSegment` adds cost terms when a connected battery's stored energy violates discharge
energy thresholds or charge capacity thresholds.
It uses slack variables to represent energy below or above thresholds, but prices the *change* in
those slacks rather than their level: entering the buffer costs, and leaving it rebates by the same
amount, so a threshold excursion is not billed again for every period it is held.
This is intended for soft, price-based incentives rather than hard operating limits.

## Model formulation

### Parameters

| Parameter              | Description                              | Units  |
| ---------------------- | ---------------------------------------- | ------ |
| $E_{\text{dis}}(t)$    | Discharge energy threshold               | kWh    |
| $E_{\text{chg}}(t)$    | Charge capacity threshold                | kWh    |
| $c_{\text{dis}}(t)$    | Discharge threshold penalty price        | \$/kWh |
| $c_{\text{chg}}(t)$    | Charge threshold penalty price           | \$/kWh |
| $E_{\text{stored}}(t)$ | Battery stored energy (model coordinate) | kWh    |

Thresholds are provided in the model coordinate system.

## Rationale and usage

SOC pricing is useful when you want the optimizer to prefer certain operating ranges without
blocking feasible solutions.
Instead of adding hard constraints, the segment adds penalties (or incentives) that scale with the
amount of energy outside a threshold.
This keeps the model feasible while still signaling "avoid going below this reserve" or "avoid
filling beyond this headroom" as economic preferences.

Use cases include:

- Reserving a discharge buffer for uncertainty while still allowing emergency draw.
- Keeping headroom for anticipated solar while still allowing full charge if prices justify it.
- Shaping charge/discharge timing by combining base prices with SOC penalties.

The thresholds use the battery's model coordinate, so they align with the battery element's stored
energy state.
If your device or UI expresses thresholds in SOC percentage, convert to energy before passing to the
segment.

### Decision variables

Slack is tracked for $t = 0 \dots n$, where $t = 0$ is the depth already present at the start of the
horizon (against the first period's threshold) and $t = 1 \dots n$ are the per-period values exposed
as outputs.

| Variable            | Domain                | Description                            |
| ------------------- | --------------------- | -------------------------------------- |
| $S_{\text{dis}}(t)$ | $\mathbb{R}_{\geq 0}$ | Energy below discharge threshold       |
| $S_{\text{chg}}(t)$ | $\mathbb{R}_{\geq 0}$ | Energy above charge capacity threshold |

### Constraints

Discharge threshold slack:

$$
S_{\text{dis}}(t) \geq E_{\text{dis}}(t) - E_{\text{stored}}(t)
$$

Charge threshold slack:

$$
S_{\text{chg}}(t) \geq E_{\text{stored}}(t) - E_{\text{chg}}(t)
$$

### Cost contribution

Priced on the period-over-period change in slack, not its level:

$$
\text{Cost} = \sum_{t=1}^{n} \left[ (S_{\text{dis}}(t) - S_{\text{dis}}(t-1)) \cdot c_{\text{dis}}(t) + (S_{\text{chg}}(t) - S_{\text{chg}}(t-1)) \cdot c_{\text{chg}}(t) \right]
$$

Deepening the excursion ($S(t) > S(t-1)$) costs at that period's price; recovering from it
($S(t) < S(t-1)$) rebates by the same amount at that period's price. A round trip into the buffer
and back out nets to zero cost regardless of how many periods it spans — only the excursion's depth
at entry and exit matters, not its duration. If the horizon ends mid-excursion, the entry cost is not
yet rebated.

## Physical interpretation

SOC pricing models an economic toll for moving outside discharge and charge thresholds, refunded for
moving back. These are soft constraints: the optimizer can violate thresholds when prices justify it,
and a brief excursion used to absorb a forecast deviation is effectively free.

## Pricing partitions with opposing thresholds

You can model pricing for a specific energy band by pairing two SOC pricing segments with opposite
signs at different thresholds.
One segment can penalize energy below a lower threshold, while another provides a negative price
above an upper threshold.
The combination creates a net incentive to keep energy inside a band, while still allowing
economically justified deviations.

For example, to encourage the battery to stay between `E_low` and `E_high`:

- Set a positive `discharge_energy_price` below `E_low`.
- Set a negative `charge_capacity_price` above `E_high`.

This produces a "reward" for staying within the band and a "cost" for leaving it.
It is still a soft signal, so it will not block solutions if other costs dominate.

## Next steps

<div class="grid cards" markdown>

- :material-connection:{ .lg .middle } **Connection model**

    ---

    Segment-based connection formulation.

    [:material-arrow-right: Connection formulation](../connections/connection.md)

- :material-layers:{ .lg .middle } **Segments**

    ---

    Browse all connection segment types.

    [:material-arrow-right: Segment index](index.md)

- :material-code-braces:{ .lg .middle } **Implementation**

    ---

    View the source code for the SOC pricing segment.

    [:material-arrow-right: Source code](https://github.com/hass-energy/haeo/blob/main/custom_components/haeo/core/model/elements/segments/soc_pricing.py)

</div>
