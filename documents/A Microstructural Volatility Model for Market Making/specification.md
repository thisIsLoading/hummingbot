# Microstructural Volatility Market-Making Strategy Specification

## 1. Purpose and Scope
- Develop a Hummingbot V2 controller that adapts quoting widths using microstructural volatility estimates derived from live order book data.
- Support both discrete regime-based spreads and continuous interpolation across volatility levels.
- Provide a foundation for future enhancements (additional signals, adaptive inventory skew, advanced risk controls) by documenting assumptions, data needs, and operational processes.

## 2. Background and References
- Primary reference: **“A Microstructural Volatility Model for Market Making”** (VertoxQuant, Aug 20, 2024). The article advocates measuring short-term midprice volatility and widening quotes as volatility rises to preserve edge.
- Key concepts pulled into this design:
  - Midprice as a proxy for fair value in the absence of an internal pricing model.
  - Rolling-window standard deviation (e.g., 30–60s) to capture microstructural variance.
  - Volatility regimes (low / medium / high) with distinct spreads.
  - Continuous interpolation between spreads to avoid abrupt regime shifts.
- Complementary Hummingbot resources:
  - `MarketMakingControllerBase` for spread management, executor orchestration, and optional position rebalancing.
  - Existing controllers (`pmm_simple`, `pmm_dynamic`) for reference on processed data handling, dynamic spreads, and triple-barrier risk controls.

## 3. Strategy Goals
**Functional**
- Dynamically adjust quoting widths as volatility evolves.
- Run in an event-driven fashion by reacting to order book updates rather than fixed polling.
- Build and maintain inventory targets automatically (e.g., accumulate BTC on zero-fee BTC/FDUSD pairs and neutralize once targets are met).
- Offer user-configurable knobs for volatility window, regime thresholds, spread curves, inventory targets, and refresh timings.

**Non-Functional**
- Maintain extensibility for new signals (imbalance, trade counts) without rewiring the controller.
- Keep risk management consistent with existing Hummingbot patterns (triple barrier, cooldowns, rebalances).
- Ensure clarity for testers: all assumptions and calibration steps are documented.

## 4. Strategy Concept and Logic
### 4.1 Market Data Ingestion
- Subscribe to the connector’s order book (`MarketDataProvider.get_order_book`).
- Attach an `EventForwarder` to `OrderBookEvent.OrderBookDataSourceUpdateEvent` (diff or snapshot).
- Each event provides best bid/ask; compute midprice and append to a rolling buffer (deque keyed by timestamp).
- Debounce updates (optional): ignore events arriving inside a configurable minimum interval unless bid/ask changed.

### 4.2 Volatility Estimation
- Maintain last `N` seconds of midprice observations (default 60s, configurable).
- Support two modes:
  1. **Absolute change:** `σ = std(mid_t - mid_{t-1})`.
  2. **Percentage change:** `σ_pct = std((mid_t - mid_{t-1}) / mid_{t-1})` (default for cross-venue comparability).
- Require a minimum number of samples before emitting spreads; otherwise fall back to a safe default width (e.g., medium regime spread).

### 4.3 Spread Determination
- **Discrete Regime Option:**
  - User specifies thresholds (e.g., `low <= σ < medium`, `medium <= σ < high`, `σ >= high`).
  - Assign spreads per regime (buy and sell) in basis points.
- **Continuous Interpolation Option:**
  - User supplies ordered `(σ_i, spread_i)` points.
  - Perform piecewise-linear interpolation for `σ` between points.
  - Enforce floor/ceiling spreads to avoid effectively zero quoting.
- The resulting `spread_multiplier` scales configured `buy_spreads` / `sell_spreads` arrays from the config (set to `1` to represent “base width”).

### 4.4 Order Placement and Refresh
- Use `MarketMakingControllerBase` mechanics:
  - `get_levels_to_execute()` filters by active executors and cooldowns.
  - `get_price_and_amount()` multiplies base spreads by `spread_multiplier` and returns sizes.
- Set `executor_refresh_time` (e.g., 15 s) to replace stale quotes leveraging the built-in refresh routine.
- Maintain `cooldown_time` (e.g., 5 s) so just-closed trades briefly wait before re-quoting.

### 4.5 Inventory Build and Neutralization
- Introduce new config inputs:
  - `inventory_target_base` (desired BTC quantity) and optional `tolerance_pct`.
  - `inventory_accumulation_mode` (e.g., `buy_only_until_target`, `skewed_spreads`, `neutral`).
- Behavior:
  - If below target, either (a) disable sell levels, or (b) keep sells wider than buys to encourage fills on the buy side.
  - When within tolerance, revert to balanced quoting.
  - If above target (due to fills), optionally favor sells until neutral.
- Pair with existing `position_rebalance_threshold_pct` and `create_position_rebalance_order` to top-up or reduce base via market orders when holdings diverge sharply from what is needed to service active sell orders.

### 4.6 Risk Controls
- Continue using triple barrier parameters (stop loss, take profit, time limit) per executor.
- Add cooldown after high-vol regime to avoid over-trading during bursts (e.g., lockout for 5 s after a volatility spike).
- Optional: limit total outstanding inventory by capping number of concurrent buy executors.
- Tracking metrics: realized vs expected spread capture, inventory PnL, volatility regime occupancy.

## 5. Architecture Overview
- Design for plug-and-play evolution: every tactical decision (volatility estimate, spread shape, inventory policy) lives behind an interface so new methods can be dropped in without touching the controller core.
- Keep responsibilities small and composable to support future signals (imbalance, trade flow) and alternative quoting logics referenced in the source article.
- Provide explicit registries and factories so configuration drives behavior instead of hard-coded classes.

### 5.1 Package Layout
```
controllers/market_making/micro_vol/
    __init__.py                # Registry exposure and factory helpers
    config.py                  # Pydantic config + CLI prompts
    controller.py              # MicroVolMMController (orchestrator)
    listeners/
        order_book.py          # EventForwarder adapter, debounce helpers
    volatility/
        base.py                # VolatilityEngine protocol / ABC
        rolling_std.py         # Default rolling standard deviation engine
        ewma.py                # Placeholder for future EWMA/GARCH variants
    spreads/
        base.py                # SpreadPolicy protocol
        discrete.py            # Quantile-based regime spreads
        linear.py              # Piecewise-linear interpolation policy
    inventory/
        base.py                # InventoryPolicy protocol
        buy_only.py            # Accumulate-to-target behavior
        skewed.py              # Spread-bias implementation for gradual neutralisation
```
This folder sits beside existing controllers and keeps strategy-specific logic self-contained while surfacing registry entry points in `controllers/market_making/__init__.py`.

### 5.2 Component Responsibilities
- **Config (`config.py`)**: extends `MarketMakingControllerConfigBase`, parses user parameters, and resolves class names to concrete implementations via registries. Encapsulates defaults described in section 6.
- **Controller (`controller.py`)**: thin orchestrator that wires together injected policies. Coordinates order-book listener lifecycle, calls the volatility engine, requests spreads from the policy, asks inventory policy for enabled sides/amount multipliers, and updates `processed_data`/executors.
- **Volatility Engines**: each class implements `update(midprice: Decimal, timestamp: float) -> Decimal`. Rolling std is the default; EWMA/GARCH placeholders demonstrate planned extension points.
- **Spread Policies**: accept `sigma`, optional metadata (e.g., inventory state), and return `SpreadDecision` objects containing bid/ask multipliers and metadata (regime label). Discrete/linear policies map article concepts; future spline/sigmoid variants plug in here.
- **Inventory Policies**: expose methods like `get_side_state(inventory_snapshot) -> InventoryDecision`, determining which sides to quote and any bias factors. `buy_only` and `skewed` cover accumulation strategies discussed above.
- **Listeners**: wrap connector order-book events, handle debounce/min interval logic, and push normalized midprice updates into the volatility engine. Keeping this separate simplifies future multi-source listeners (e.g., trade tape, imbalance feed).

### 5.3 Runtime Interaction Flow
1. Listener receives order-book diff/snapshot, extracts midprice, and calls the volatility engine.
2. Engine updates rolling window and returns current `sigma`; listener notifies controller via an async callback.
3. Controller computes inventory snapshot (positions + balances), asks inventory policy for permissible sides/bias, and requests spread policy output using `sigma` and bias info.
4. Controller updates `processed_data` (`reference_price`, `spread_multiplier`, plus diagnostics) and lets `MarketMakingControllerBase` drive executor creation/refresh.
5. Position rebalancing remains delegated to the base class, but policies can request overrides (e.g., pause sells) through their return objects.

### 5.4 Rationale & Extension Readiness
- Separating volatility, spread, and inventory logic mirrors the article’s modular presentation (volatility measurement, discrete vs continuous spread control) and lets us track enhancements listed in Section 11 without controller rewrites.
- Interface-driven design means future features—spline fits, logistic spread curves, order-book imbalance adjusters—become additional policy classes packaged under the same directory structure.
- Clear file boundaries ease testing: each policy/engine gets focused unit tests, while controller integration tests mock interfaces to simulate edge cases.
- Registries allow dynamic selection from config/CLI, keeping the experience “enterprise grade” by avoiding hard-coded strategy names and encouraging contribution of new modules.

## 6. Parameter Overview
| Category | Parameter | Description | Initial Default |
| --- | --- | --- | --- |
| Volatility | `vol_window_seconds` | Rolling window length for volatility computation | 60 |
| Volatility | `vol_mode` | `absolute` or `percentage` change | `percentage` |
| Volatility | `min_samples` | Minimum observations before enabling dynamic spreads | 10 |
| Regimes | `low_threshold`, `medium_threshold`, `high_threshold` | σ cutoffs for discrete mode | 0.0005, 0.0015, 0.003 |
| Regimes | `spread_low`, `spread_medium`, `spread_high` | Bid/ask widths (bps) for discrete mode | 4, 8, 20 |
| Interp | `spread_curve_points` | Ordered pairs `(σ, spread_bps)` for continuous mode | Example: (0.0002, 3), (0.0008, 6), (0.0025, 15) |
| Order Flow | `executor_refresh_time` | Seconds before cancelling and relaunching stale orders | 15 |
| Order Flow | `cooldown_time` | Seconds to wait after a filled executor | 5 |
| Inventory | `inventory_target_base` | Desired base holding (BTC) | 0.002 |
| Inventory | `inventory_tolerance_pct` | Band around target before rebalancing | 0.1 |
| Inventory | `inventory_accumulation_mode` | `buy_only`, `skewed`, `neutral` | `buy_only` |
| Event Handling | `min_update_interval` | Minimum seconds between reactions to OB events | 0.05 |

Defaults will be tuned during calibration; table serves as baseline for test deployment on BTC/FDUSD.

## 7. Operating Modes and Scenarios
- **Low Volatility:** Tight spreads (e.g., 3–4 bps), both sides active, target fill rate high, inventory near target.
- **Medium Volatility:** Wider spreads (6–10 bps), optionally reduce number of levels to cut inventory churn.
- **High Volatility:** Spread floor near 20 bps, optionally disable quote updates for `lockout_seconds` to avoid knife-catching.
- **Inventory Build Stage:** Only buy ladder wide enough to respect Binance tick size; sells disabled until target reached.
- **Recovery Mode:** If volatility > `panic_threshold`, pause quoting until stable sample count observed.

## 8. Calibration and Analytics
1. **Data Capture**
   - Log volatility values, regime labels, spreads, fills, and inventory in CSV/DB for back-analysis.
   - Capture raw order book snapshots at 100 ms cadence when feasible for offline replay.
2. **Parameter Selection Workflow**
   - Run historical simulations (LOB replay) to test regime cutoffs; aim for consistent realized edge net of fees.
   - Optimize interpolation curve by minimizing aggressiveness during calm while meeting fill targets.
   - Validate inventory target sizing vs. Binance minimums and risk appetite.
3. **Monitoring Metrics**
   - Spread capture (realized vs quoted), fill ratio per regime, inventory mean and variance, PnL by regime, volatility prediction error.

## 9. Testing Plan
- **Unit Tests**
  - Volatility buffer updates (window trim, sample count, σ outputs in both modes).
  - Regime classifier & interpolation logic across edge cases.
  - Inventory mode transitions (buy-only → neutral; tolerance enforcement).
- **Integration Tests**
  - Simulate order book feed to ensure event-driven updates trigger controller actions.
  - Confirm processed data shapes align with `MarketMakingControllerBase` expectations.
  - Validate position rebalance actions fire only when thresholds breached.
- **Paper Trading / Dry Run**
  - Deploy on Binance Testnet or low-size live environment; verify no fees on FDUSD pair.
  - Monitor logs for regime transitions, spread adjustments, inventory build.
- **Production Pilot**
  - Start with minimal quote capital (e.g., 50 FDUSD) and tight risk limits.
  - Enable alerting on volatility spikes, inventory excursions, or repeated execution failures.

## 10. Deployment & Operations
1. **Pre-Launch Checklist**
   - Configure controller via `make run-v2` parameters or config file.
   - Ensure Binance connector API keys present and trading rules fetched.
   - Seed BTC/FDUSD balances exceeding minimum trade notional.
2. **Runtime Monitoring**
   - Stream logs for regime changes, inventory state, error messages.
   - Track PnL and inventory via Hummingbot status commands.
   - Set manual kill switch if volatility remains in panic state > configured horizon.
3. **Post-Session Review**
   - Export daily metrics for calibration feedback loop.
   - Re-tune thresholds if realized edge diverges from target.

## 11. Future Enhancements
- Incorporate additional microstructure signals (order book imbalance, trade count bursts, spread skew).
- Replace simple rolling σ with exponentially weighted or GARCH-style estimator for better responsiveness.
- Layer adaptive inventory skew based on predictive drift (e.g., MACD, funding signals).
- Introduce multi-venue routing where volatility drives hedging between correlated markets.
- Add configurable partial fill / queue position awareness by sampling depth levels.

## 12. Open Questions & Assumptions
- Fee waiver availability on BTC/FDUSD is assumed; must verify continues for target accounts.
- Latency expectations: relying on connector order book updates (~100 ms). If slower, consider direct WebSocket taps.
- Inventory finance: specification assumes no leverage; adapt if deploying on perpetuals.
- Execution risk during extreme volatility: need decision on whether to auto-disable strategy when order book thinness crosses threshold (e.g., depth < X BTC within ±10 bps).

---
This specification should be revisited after initial calibration and paper-trading cycles to capture empirical learnings and refine thresholds, default parameters, and operational safeguards.
