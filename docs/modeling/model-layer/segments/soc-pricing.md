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
as outputs. An outstanding-toll variable $P(t)$ tracks the not-yet-rebated cost of the current
excursion.

| Variable            | Domain                | Description                             |
| ------------------- | --------------------- | ---------------------------------------- |
| $S_{\text{dis}}(t)$ | $\mathbb{R}_{\geq 0}$ | Energy below discharge threshold        |
| $S_{\text{chg}}(t)$ | $\mathbb{R}_{\geq 0}$ | Energy above charge capacity threshold  |
| $P_{\text{dis}}(t)$ | $\mathbb{R}_{\geq 0}$ | Outstanding discharge toll, $t=0\dots n$ |
| $P_{\text{chg}}(t)$ | $\mathbb{R}_{\geq 0}$ | Outstanding charge toll, $t=0\dots n$    |

### Constraints

Discharge threshold slack:

$$
S_{\text{dis}}(t) \geq E_{\text{dis}}(t) - E_{\text{stored}}(t)
$$

Charge threshold slack:

$$
S_{\text{chg}}(t) \geq E_{\text{stored}}(t) - E_{\text{chg}}(t)
$$

Outstanding toll, floored at zero so a recovery can never rebate more than was actually paid in.
Index 0 is the base case of the same relation — treating the implicit $S(-1)$ and $P(-1)$ before the
horizon as zero — so a real pre-existing excursion ($S(0) > 0$) already owes $c(0) \cdot S(0)$ before
the horizon even starts, rather than being pinned to zero:

$$
P_{\text{dis}}(0) \geq c_{\text{dis}}(0) \cdot S_{\text{dis}}(0), \qquad P_{\text{dis}}(t) \geq P_{\text{dis}}(t-1) + c_{\text{dis}}(t) \cdot \left(S_{\text{dis}}(t) - S_{\text{dis}}(t-1)\right) \quad (t \geq 1)
$$

(and symmetrically for $P_{\text{chg}}$). Minimizing $P(n)$ forces this chain — together with
$P(t) \geq 0$ — to its tightest feasible value at every step, which is exactly
$P(t) = \max(0,\, P(t-1) + c(t) \cdot \Delta S(t))$: deepening the excursion raises the toll,
recovering from it lowers it, and the floor stops it from going negative.

This same chain also pins every $S(t)$ to its true minimal, data-driven value: minimizing $P(n)$
transitively wants every earlier $P(t)$ — and hence every $S(t)$, via its strictly positive price
coefficient at each step — as small as feasible. This matters because pinning $P(0)$ to exactly zero
instead would leave $S(0)$ with no upper bound and no cost, letting it be inflated to manufacture
unlimited rebate against a real violation later in the horizon.

### Cost contribution

Only the final outstanding toll is priced:

$$
\text{Cost} = P_{\text{dis}}(n) + P_{\text{chg}}(n)
$$

A round trip into the buffer and back out nets to zero cost regardless of how many periods it
spans or how deep it went — only the excursion's net recovery matters, not its duration. If the
horizon ends mid-excursion, or a recovery only partially offsets an earlier excursion, the
unrebated remainder stays in the cost. A pre-existing excursion that is already priced in at $t=0$
(see above) is rebated the same way as one entered during the horizon.

This pricing is exact when the price is constant across the horizon (the common case — this field is
typically a fixed penalty rate rather than a real-time tariff). With a genuinely time-varying price, a
small, bounded mispricing is possible: recovering during a period priced differently from when the
excursion was entered rebates at the recovery period's price, not the original entry price.

## Physical interpretation

SOC pricing models an economic toll for moving outside discharge and charge thresholds, refunded for
moving back — capped so you can never be rebated more than you paid in. These are soft constraints:
the optimizer can violate thresholds when prices justify it, and a brief excursion used to absorb a
forecast deviation is effectively free.

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
