p# Hummingbot Strategy V2 Philosophy and Architecture

## Core Philosophy

Strategy V2 represents a fundamental shift from monolithic strategy design to a **modular, component-based architecture
**. The system follows these key principles:

1. **Separation of Concerns**: Strategy logic (Controllers) is separated from execution logic (Executors)
2. **Asynchronous Event-Driven Design**: Components communicate through queues and events
3. **Modularity**: Lego-like components that can be combined to create complex strategies
4. **State Persistence**: Executors and positions are stored in database for recovery
5. **Multi-Market Support**: Single bot can manage multiple exchanges and trading pairs simultaneously

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    StrategyV2Base                           │
│  - Orchestrates all components                              │
│  - Manages lifecycle                                        │
│  - Handles configuration updates                            │
└──────────────────┬──────────────────────────────────────────┘
                   │
    ┌──────────────┼──────────────┬────────────────┐
    ▼              ▼              ▼                ▼
┌──────────┐ ┌──────────┐ ┌─────────────┐ ┌──────────────┐
│Controllers│ │ Market   │ │  Executor   │ │   Market     │
│           │ │  Data    │ │Orchestrator │ │  Recorder    │
│           │ │ Provider │ │             │ │              │
└──────────┘ └──────────┘ └─────────────┘ └──────────────┘
     │                           │
     └───── Actions Queue ───────┘
```

## Key Components

### 1. RunnableBase (`/hummingbot/strategy_v2/runnable_base.py`)

The foundation for all async components in V2:

- Provides a control loop that executes at regular intervals
- Manages component lifecycle (start, stop, status)
- Handles errors gracefully without crashing
- Status tracking: NOT_STARTED → RUNNING → TERMINATED

### 2. Controllers (`/hummingbot/strategy_v2/controllers/`)

Controllers are the **brain** of the strategy - they decide WHAT to do:

#### ControllerBase

- Abstract base class for all controllers
- Processes market data to determine trading decisions
- Sends ExecutorActions through an actions queue
- Updates processed data at regular intervals
- Can be dynamically updated without restart

#### Specialized Controllers

- **MarketMakingControllerBase**: For market making strategies with bid/ask spreads
- **DirectionalTradingControllerBase**: For trend-following and directional strategies

Key responsibilities:

- Process candles and market data
- Determine when to create/stop/store executors
- Manage risk parameters (stop loss, take profit, time limits)
- Handle position sizing and leverage

### 3. Executors (`/hummingbot/strategy_v2/executors/`)

Executors are the **hands** of the strategy - they execute HOW to do it:

#### Types of Executors

- **PositionExecutor**: Manages a single position with triple barrier (TP/SL/Time)
- **GridExecutor**: Implements grid trading strategies
- **DCAExecutor**: Dollar cost averaging executor
- **ArbitrageExecutor**: Cross-exchange arbitrage
- **TWAPExecutor**: Time-weighted average price execution
- **XEMMExecutor**: Cross-exchange market making
- **OrderExecutor**: Simple order execution

#### Executor Lifecycle

1. Created by controller via CreateExecutorAction
2. Manages its own orders and position
3. Reports status back to orchestrator
4. Can be stopped (StopExecutorAction) or stored (StoreExecutorAction)

### 4. Executor Orchestrator (`/hummingbot/strategy_v2/executors/executor_orchestrator.py`)

The **coordinator** that manages all executors:

- Maintains active executors per controller
- Tracks positions held across all executors
- Calculates performance metrics
- Handles executor lifecycle (create, stop, store)
- Manages position recovery from database

Key features:

- Caches performance metrics for efficiency
- Tracks cumulative PnL and fees
- Manages held positions separately from active positions
- Provides unified reporting to controllers

### 5. Market Data Provider (`/hummingbot/data_feed/market_data_provider.py`)

Centralized data source for all controllers:

- Manages candles feeds for multiple exchanges
- Provides real-time and historical market data
- Ensures data consistency across components

### 6. Actions System

Communication between controllers and executors via typed actions:

```python
ExecutorAction(base)
├── CreateExecutorAction  # Create new executor with config
├── StopExecutorAction  # Stop executor (optionally keep position)
└── StoreExecutorAction  # Store executor to database
```

## Data Flow

1. **Market Data** → Market Data Provider → Controllers
2. **Controllers** analyze data → Generate ExecutorActions
3. **Actions Queue** → Executor Orchestrator
4. **Orchestrator** → Creates/manages Executors
5. **Executors** → Place/manage orders on exchanges
6. **Order Events** → Update executor state
7. **Performance Metrics** → Back to Controllers

## Key Design Patterns

### 1. Event-Driven Architecture

- Components communicate via events and queues
- Asynchronous processing prevents blocking
- Event forwarders handle cross-component communication

### 2. Configuration-Driven Behavior

- Controllers and executors configured via Pydantic models
- Configurations can be loaded from YAML files
- Runtime updates supported for certain parameters

### 3. State Management

- Executors track orders as TrackedOrder objects
- Positions stored in database via MarketsRecorder
- Recovery supported after bot restart

### 4. Triple Barrier Pattern

Most executors implement triple barrier risk management:

- **Take Profit**: Exit at target profit
- **Stop Loss**: Exit at maximum loss
- **Time Limit**: Exit after time expires

### 5. Position Tracking

Two types of positions:

- **Active Positions**: Currently managed by executors
- **Held Positions**: Closed executors but position kept

## Advantages Over V1

1. **Modularity**: Mix and match components
2. **Scalability**: Multiple controllers in single bot
3. **Persistence**: Survives restarts
4. **Flexibility**: Dynamic configuration updates
5. **Risk Management**: Built-in triple barrier
6. **Performance**: Efficient caching and reporting
7. **Testability**: Components can be tested independently

## Configuration Hierarchy

```
StrategyV2ConfigBase
├── markets: Dict[str, Set[str]]  # Exchange → Trading pairs
├── candles_config: List[CandlesConfig]  # Data feeds
└── controllers_config: List[str]  # Controller config files

ControllerConfigBase
├── id: str  # Unique identifier
├── controller_name: str  # Controller implementation
├── controller_type: str  # generic/market_making/directional
├── candles_config: List[CandlesConfig]
└── initial_positions: List[InitialPositionConfig]
```

## Implementation Guidelines

### Creating a Custom Controller

1. Inherit from appropriate base (ControllerBase, MarketMakingControllerBase, etc.)
2. Implement `update_processed_data()` to process market data
3. Implement `determine_executor_actions()` to generate actions
4. Define configuration class inheriting from ControllerConfigBase

### Creating a Custom Executor

1. Inherit from ExecutorBase
2. Implement order management logic
3. Define configuration class inheriting from ExecutorConfigBase
4. Register in ExecutorOrchestrator._executor_mapping

### Best Practices

1. **Use existing executors** when possible rather than creating new ones
2. **Keep controllers focused** on decision logic, not execution
3. **Leverage the triple barrier** for risk management
4. **Store critical state** in database for recovery
5. **Use configuration files** for production deployments
6. **Monitor performance metrics** via controller reports

## Database Integration

Strategy V2 integrates with MarketsRecorder for persistence:

- Executors stored with full configuration and state
- Positions tracked with PnL and fees
- Controller configurations persisted
- Automatic recovery on restart

## Future Evolution

The V2 architecture is designed for extensibility:

- New executor types can be added without modifying core
- Controllers can implement any trading logic
- Market data providers can support new data sources
- Actions system can be extended with new action types

This modular architecture enables rapid development of sophisticated trading strategies while maintaining code quality
and reusability.
