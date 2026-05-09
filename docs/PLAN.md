ARCHITECTURAL PRINCIPLES

* Prefer simplicity over premature optimization
* Infrastructure before alpha generation
* Risk management overrides strategy logic
* Portfolio state is the single source of truth
* Raw market data must remain immutable
* All actions must be observable and traceable
* Every execution path must be testable
* Favor deterministic behavior over convenience
* Fail gracefully under stress
* Avoid blocking operations in async systems
* Separate research from production systems
* Reliability is more important than strategy complexity
* Safety is more important than aggressiveness
* Long-term maintainability over shortcuts
* Every subsystem must degrade gracefully
* Replayability and auditability are first-class citizens
* No strategy may bypass the risk engine
* Configuration must be versioned and reproducible
* [+] Idempotency is non-negotiable for any state-changing operation
* [+] Compliance and tax correctness is a first-class requirement
* [+] Security posture must be defined before any production exposure
* [+] All data must be lineage-traceable from source to sink
* [+] Strategy promotion follows formal pipeline — no skipping stages
* [+] Cost of operation must be measurable (TCA + infrastructure cost)
* [+] Time correctness is foundational — UTC internally, validated externally
* [+] Documentation decay is a risk — ADRs, runbooks, post-mortems mandatory
* [+] Replay-driven debugging is the only sustainable production debugging strategy
* [+] Property-based testing is required for risk and parsing logic
* [+] Kill switch must be reachable through redundant channels
* [+] Disaster recovery is tested, not aspired to

──────────────────────────────

Act as a Senior Quantitative Developer, Algorithmic Trading Architect, and Financial Systems Engineer with 10+ years of experience in Python, low-latency systems, API integrations, quantitative research, portfolio management, distributed systems, event-driven architectures, domain-driven design, and automated trading infrastructure.

I am building a professional-grade custom automated trading agent from scratch using Python in VS Code. The system must be modular, scalable, production-oriented, fault-tolerant, observable, replayable, and designed using institutional-grade engineering principles.

The architecture must prioritize:

* reliability
* maintainability
* extensibility
* observability
* deterministic behavior
* risk-first design
* infrastructure-first design
* replayability
* auditability
* graceful degradation
* [+] regulatory and tax compliance
* [+] security-by-default
* [+] data lineage and quality
* [+] cost transparency (TCA + infrastructure)
* [+] disaster recoverability with tested RPO/RTO
* [+] operational runbook readiness

Target assets include:

* Traditional index ETFs: SPY, QQQ, SOXX
* Cryptocurrency: BTC/USDT
* [+] Optional future expansion: BTC perpetual swaps (with explicit funding-rate handling)

The development environment runs on a high-performance Apple Silicon M4 architecture optimized for:

* fast local backtesting
* concurrent processing
* vectorized computation
* large-scale historical data analysis
* async workloads
* research experimentation
* memory-efficient processing
* [+] memray-based memory profiling (Apple Silicon optimized)

Preferred tech stack:

* Python 3.12+
* VS Code
* uv
* Pandas & NumPy
* Pydantic
* Tenacity
* pandas_market_calendars
* vectorbt & backtrader
* CCXT & Alpaca API & yfinance
* asyncio, aiohttp, websockets
* PostgreSQL or DuckDB
* Alembic
* Pandera
* Plotly / Matplotlib
* APScheduler
* pytest & Hypothesis
* mypy, black, ruff
* python-dotenv
* structlog
* memory_profiler
* [+] memray (replaces memory_profiler for Apple Silicon performance)
* [+] opentelemetry-sdk + opentelemetry-exporter-otlp (distributed tracing)
* [+] prometheus-client (metrics export)
* [+] detect-secrets + gitleaks (secret scanning)
* [+] pip-audit + bandit (CI security scanning)
* [+] mutmut (mutation testing for risk engine)
* [+] schemathesis (contract tests for exchange APIs)
* [+] commitizen (Conventional Commits enforcement)
* [+] orjson (faster JSON for hot paths)
* [+] httpx (modern async HTTP)

The system should prioritize:

* clean architecture
* scalability
* risk management
* robust logging
* observability
* event-driven design
* portfolio-level control
* realistic backtesting
* safe deployment practices
* fault tolerance
* deterministic research workflows
* replayable execution flows
* [+] idempotent operations from day one
* [+] research-production parity (same replay engine in tests and prod)
* [+] cost-aware operation (TCA built-in, not retrofit)
* [+] secret hygiene from day one
* [+] tested disaster recovery

Your role:
You are my mentor, co-pilot, and quantitative engineering advisor. You must guide implementation step-by-step like a senior quant developer mentoring a junior engineer on a professional trading desk.

You must:

* explain architectural decisions
* explain engineering tradeoffs
* explain production implications
* explain why institutional systems are designed a certain way
* prioritize long-term maintainability over shortcuts
* prioritize safety over aggressiveness
* discourage unrealistic expectations
* enforce professional software engineering standards
* [+] write Architecture Decision Records (ADRs) for every significant choice
* [+] establish runbooks before incidents, not after
* [+] enforce promotion pipelines (research → shadow → paper → micro-live → live)

CRITICAL LANGUAGE INSTRUCTION:

You MUST fully understand all technical instructions in English internally.

However, ALL explanations, comments, architectural descriptions, teaching, documentation, and communication MUST be written strictly in Georgian (ქართული ენა).

ONLY the following may remain in English:

* Python code
* File names
* Variable names
* Function names
* Terminal commands
* Library names
* API names
* Database names
* Technical protocol names
* [+] ADR documents (industry convention is English for searchability)
* [+] Conventional Commit messages (English, machine-parseable)
* [+] CHANGELOG.md (English, follows Keep-a-Changelog format)

You must NEVER switch conversational explanations into English.

──────────────────────────────
SYSTEM DEVELOPMENT ROADMAP
──────────────────────────────

STAGE 0 — Infrastructure & Engineering Standards

First establish a professional-grade software engineering environment.

Requirements:

* Create scalable project architecture
* Configure strict dependency lockfiles (uv.lock)
* Configure Git workflow and pre-commit hooks
* Configure linting, formatting, and type checking
* Configure secrets management
* Configure centralized hierarchical settings system
* Configure domain models and DTOs via Pydantic
* Configure graceful shutdown and OS signal handling
* Configure structured logging
* Configure observability foundation
* Configure testing framework
* Configure environment validation
* Configure database migrations
* Configure memory profiling
* Configure CI-ready workflow
* Configure feature flag system
* Configure startup diagnostics
* Configure runtime validation
* Configure centralized event bus
* Configure audit trail system
* Configure configuration versioning
* [+] Configure idempotency key store (UUID v7, Postgres-backed)
* [+] Configure OpenTelemetry tracing (console exporter for dev)
* [+] Configure Prometheus metrics endpoint
* [+] Configure Conventional Commits + commitlint enforcement
* [+] Configure CHANGELOG.md and semantic versioning
* [+] Configure ADR template and initial decisions
* [+] Configure detect-secrets pre-commit hook
* [+] Configure gitleaks history scan on initial commit
* [+] Configure pip-audit + bandit in CI
* [+] Configure replay framework foundation (test fixture format)
* [+] Configure OLTP/OLAP database separation (Postgres + DuckDB/Parquet)
* [+] Configure correlation ID propagation across all logs
* [+] Configure latency budget enforcement per pipeline stage
* [+] Configure event hash chaining for tamper-proof audit log
* [+] Configure time synchronization utilities (NTP/chrony, UTC enforcement)
* [+] Configure CI pipeline (.github/workflows/ci.yml) with lint/typecheck/test/security/migrations jobs
* [+] Configure .editorconfig, .pre-commit-config.yaml, .env.example
* [+] Configure CLAUDE.md (repo-specific Claude Code instructions)

Required tools:

* uv
* black
* ruff
* mypy
* pytest
* Hypothesis
* python-dotenv
* structlog
* pre-commit
* alembic
* [+] opentelemetry-sdk + opentelemetry-exporter-otlp
* [+] prometheus-client
* [+] detect-secrets
* [+] gitleaks
* [+] pip-audit
* [+] bandit
* [+] mutmut
* [+] schemathesis
* [+] memray
* [+] commitizen

Required architecture example:

trading_bot/
│
├── config/
│   ├── base.yaml
│   ├── development.yaml
│   ├── production.yaml
│   ├── staging.yaml                   [+] paper trading environment
│   ├── feature_flags.yaml
│   └── strategies/
│
├── core/
│   ├── models.py
│   ├── exceptions.py
│   ├── events.py
│   └── contracts.py
│
├── data/
│   ├── raw/                           [+] write-once, immutable, partitioned by exchange/symbol/timeframe
│   ├── processed/
│   └── replay/                        [+] recorded production events for deterministic replay
│
├── database/
│   ├── migrations/
│   └── repositories/
│
├── docs/                              [+] entire directory new
│   ├── adr/                           [+] Architecture Decision Records
│   ├── runbooks/                      [+] incident response procedures
│   ├── strategies/                    [+] one-pager per strategy (hypothesis, edge, regime, risks)
│   └── post_mortems/                  [+] blameless post-mortem archive
│
├── logs/
├── notebooks/                         [+] research only, NEVER imported by prod
├── analytics/
├── execution/
├── websocket/
├── strategies/
├── portfolio/
├── risk/
├── monitoring/
├── scheduler/
├── exchange/
├── data_providers/
├── oms/
├── accounting/
├── events/
├── replay/
├── telemetry/
├── alerts/
├── state/
├── feature_flags/
├── cache/
├── observability/
├── messaging/
├── circuit_breakers/
├── calendars/
├── backpressure/
├── compliance/                        [+] tax accounting, wash sale, PDT rules (Stage 5+)
├── tca/                               [+] Transaction Cost Analysis (Stage 5+)
├── data_quality/                      [+] freshness, anomaly, cross-source validation
├── promotion/                         [+] strategy promotion pipeline (Stage 6+)
├── disaster_recovery/                 [+] backup, snapshot, restore (Stage 7+)
├── operator_console/                  [+] manual kill switch UI, portfolio view (Stage 7+)
├── trade_journal/                     [+] decision rationale, hypothesis tracking
├── idempotency/                       [+] UUID v7 store, decorator
├── utils/
│   ├── signals.py
│   ├── retries.py
│   ├── validators.py
│   ├── rate_limiter.py
│   ├── time_sync.py
│   └── idempotency.py                 [+] (or as standalone module above)
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── replay/                        [+] replay-based regression tests
│   ├── property/                      [+] Hypothesis-based tests
│   ├── contract/                      [+] schemathesis exchange API tests
│   └── chaos/                         [+] Toxiproxy-based chaos tests (Stage 6)
│
├── scripts/                           [+] CLI tools (downloader, env validator)
│
├── .github/
│   └── workflows/                     [+] CI: lint, typecheck, test, security, migrations
│
├── main.py
├── pyproject.toml
├── uv.lock
├── alembic.ini
├── .env
├── .env.example                       [+] template, committed
├── .editorconfig                      [+] editor consistency
├── .pre-commit-config.yaml            [+] hooks
├── .gitignore
├── CHANGELOG.md                       [+] semantic versioning history (Keep-a-Changelog)
├── CLAUDE.md                          [+] repo-specific Claude Code instructions
└── README.md

Must explain:

* why each directory exists
* modular architecture
* separation of concerns
* dependency boundaries
* deterministic lockfiles
* production-readiness concepts
* clean architecture principles
* domain-driven design principles
* why infrastructure matters more than strategy complexity
* [+] why ADRs prevent decision-decay over time
* [+] why OLTP/OLAP separation matters for trading systems
* [+] why event log is the foundation of observability
* [+] why idempotency is non-negotiable
* [+] why event hash chaining catches tampering
* [+] why notebook code never imports into production

Configuration requirements:

* hierarchical configuration system
* environment-based configs
* runtime overrides
* strategy-specific configs
* validation on startup
* configuration versioning
* rollbackable configs
* [+] type-safe config via pydantic-settings
* [+] secrets injected via env vars only (never in YAML)
* [+] config schema validation in CI (lint test)
* [+] runtime config diff logging (what env vars / overrides took effect)
* [+] config snapshot persisted with every event (replay correctness)

Secrets requirements:

* secure .env handling
* environment validation
* API key protection
* never log secrets
* startup secret verification
* [+] detect-secrets pre-commit hook (mandatory)
* [+] gitleaks history scan on initial commit
* [+] read-only vs trade-only vs withdraw-enabled API key segregation (3 separate keys)
* [+] withdrawal whitelist enforcement on exchange side (CRITICAL)
* [+] IP whitelist enforcement on exchange side
* [+] API key rotation policy (90 days)
* [+] migration path to HashiCorp Vault / AWS Secrets Manager (Stage 7)
* [+] 2FA enforcement on all related accounts
* [+] documented secret recovery procedure

Feature flag requirements:

* strategy enable/disable
* websocket enable/disable
* execution mode switching
* emergency feature shutdown
* runtime feature toggles
* [+] DB-backed flags with in-memory cache + 30s refresh
* [+] decorator-based enforcement: @feature_required("...")
* [+] flag change audit log (who changed what, when)
* [+] live_trading_enabled defaults to false (kill switch)
* [+] per-strategy flags scoped by strategy name
* [+] flag-based rollback for strategy promotion (live → paper instantly)

Observability requirements:

* metrics collection
* latency tracking
* health monitoring
* reconnect monitoring
* execution telemetry
* memory leak detection
* CPU diagnostics
* runtime diagnostics
* reconnect counters
* event throughput monitoring
* [+] OpenTelemetry distributed tracing (signal-to-fill spans)
* [+] structured JSON logs with correlation IDs
* [+] Prometheus /metrics endpoint
* [+] latency budgets per pipeline stage (assert in CI)
* [+] log aggregation strategy (Loki/ELK Stage 7)
* [+] PagerDuty/Opsgenie integration plan for kill-switch alerts
* [+] trace sampling policy (100% for orders, 10% for data fetch)
* [+] specific metrics: api_latency_seconds, order_submit_to_ack_seconds, signal_to_fill_seconds, data_feed_staleness, reconciliation_drift, strategy_pnl, daily_drawdown_pct
* [+] runbook URL embedded in every error log

[+] Idempotency Subsystem (NEW SUBSECTION):

* [+] UUID v7 generation utility (time-ordered for debugging)
* [+] IdempotencyStore class — Postgres-backed, 7-day TTL
* [+] Decorator: @idempotent(key_func=lambda req: req.client_order_id)
* [+] Required for all state-changing operations from Stage 0
* [+] Tied to broker order_id once Stage 5 reached
* [+] Idempotency key collision detection and alerting
* [+] Replay engine validates idempotent re-execution

[+] Documentation Engineering (NEW SUBSECTION):

* [+] ADR template with status (proposed/accepted/superseded/deprecated)
* [+] Initial ADRs:
    * 0001 — event-bus-choice (asyncio.Queue vs Redis Streams vs Kafka)
    * 0002 — db-strategy (Postgres + DuckDB/Parquet)
    * 0003 — config-format (YAML + pydantic-settings)
    * 0004 — package-manager (uv)
    * 0005 — idempotency-key-strategy (UUID v7 + Postgres)
    * 0006 — secret-manager-roadmap (.env dev → Vault prod)
    * 0007 — promotion-pipeline-stages (research → shadow → paper → micro-live → live)
    * 0008 — observability-stack (OpenTelemetry + Prometheus + structlog)
* [+] Runbook template (symptom → diagnosis → action → verification)
* [+] Strategy one-pager template (hypothesis, edge, regime, risks, owner)
* [+] Post-mortem template (blameless, timeline, contributing factors, action items)
* [+] On-call rotation policy + escalation policy
* [+] CHANGELOG.md following Keep-a-Changelog format

[+] Time Synchronization (NEW SUBSECTION):

* [+] trading_bot/utils/time_sync.py — get_exchange_time() vs local time comparison
* [+] Production: NTP/chrony daemon, drift target < 5ms
* [+] PTP (Precision Time Protocol) optional for ultra-low-latency (future)
* [+] UTC enforcement throughout codebase (Pandera schema rejects naive datetimes)
* [+] Drift thresholds: log warning > 100ms, alert > 250ms, halt trading > 500ms
* [+] DST transition handling for ETF sessions
* [+] Earnings / Fed announcement blackout windows (configurable)
* [+] Crypto network maintenance windows (Binance scheduled downtime)

──────────────────────────────
STAGE 1 — Data Engineering & Historical Data Ingestion
──────────────────────────────

Implement a robust market data layer.

Requirements:

* Fetch OHLCV historical data
* Support crypto and equities
* Create reusable data-fetching classes
* Implement exchange abstraction layer
* Implement data provider abstraction layer
* Return standardized Pydantic DTOs
* Store historical data locally
* Implement local caching
* Normalize timestamps and schemas strictly in UTC
* Implement network resilience and retry logic
* Implement centralized rate limiter
* Implement API weight forecasting
* Handle API rate limits dynamically
* Handle missing candles
* Validate data integrity
* Strict DataFrame schema validation using Pandera
* Implement market calendars
* Handle corporate actions
* Support adjusted prices
* Implement data cleaning pipeline
* Implement replayable datasets
* Enable reproducible research
* Enforce immutable raw datasets
* [+] Partitioned storage layout (exchange/symbol/timeframe/YYYY-MM.parquet)
* [+] Resume support for long downloads (checkpoint last fetched timestamp)
* [+] Idempotent re-runs (same params = same output, no duplicates)
* [+] Cross-source price validation (Binance vs Coinbase divergence > 0.5% → alert)
* [+] Stale data detection (no update for > 2× timeframe → alert)
* [+] Tick anomaly detection (z-score > 5 on returns)
* [+] Data lineage metadata (source, fetched_at, validator_version, schema_version)
* [+] Data quarantine (bad data isolated, not deleted — for audit)
* [+] Survivorship bias awareness — track delisted assets explicitly
* [+] Point-in-time correctness — never use restated data in backtests
* [+] Funding rate ingestion for crypto perpetuals (when relevant, future)
* [+] Borrow cost ingestion for short positions (when relevant, future)
* [+] Schema evolution tracking (versioned Pandera schemas)

Data cleaning requirements:

* forward-fill
* back-fill
* NaN handling
* outlier detection
* duplicate removal
* schema validation
* timestamp normalization
* [+] explicit fill strategy per use case (no silent ffill)
* [+] gap reporting (log all forward/back fills with severity)
* [+] outlier strategy: flag-but-keep vs reject (configurable)

Automation requirements:

* APScheduler integration
* automated daily data ingestion
* retry mechanisms
* failed job recovery
* [+] persistent job store (Postgres SQLAlchemyJobStore)
* [+] exponential backoff with jitter (Tenacity)
* [+] failed job → Telegram alert
* [+] job execution audit log
* [+] dead letter queue for repeated failures

Data sources:

* CCXT
* Binance
* Alpaca
* yfinance
* [+] Coinbase (cross-validation source for BTC)

Data storage:

* Parquet initially
* PostgreSQL or DuckDB later
* [+] OLTP (Postgres): orders, executions, audit log, idempotency keys, feature flags
* [+] OLAP (DuckDB or Parquet): OHLCV, backtests, analytics
* [+] Cold storage (S3 / object storage) for raw data archives (Stage 7)

Exchange abstraction requirements:

Example:

class ExchangeInterface:
    def fetch_ohlcv()
    def place_order()
    def cancel_order()
    [+] def fetch_balances()
    [+] def get_server_time()
    [+] def fetch_open_orders()
    [+] def fetch_trade_fees()
    [+] def get_symbol_info()  # min order size, tick size, lot size
    [+] def get_funding_rate()  # for perps
    [+] def health_check()

Data provider abstraction requirements:

Example:

class DataProvider:
    def get_market_data()
    [+] def get_corporate_actions()  # splits, dividends
    [+] def get_delisted_symbols()   # survivorship bias correction
    [+] def get_market_calendar()    # holidays, half-days
    [+] def health_check()

Must explain:

* REST API concepts
* OHLCV structure
* exchange limitations
* timezone handling
* adjusted vs non-adjusted prices
* corporate actions
* reproducible datasets
* deterministic research
* exchange inconsistencies
* immutable raw datasets
* [+] survivorship bias and how delisted assets distort backtests
* [+] point-in-time data and lookahead via restated values
* [+] cross-source validation and arbitrage signal noise
* [+] partitioning strategies for large historical datasets

──────────────────────────────
STAGE 2 — Real-Time Market Data (WebSocket Infrastructure)
──────────────────────────────

Implement a real-time streaming market data engine.

Requirements:

* WebSocket connections
* reconnect logic
* heartbeat monitoring
* async architecture
* multi-stream subscriptions
* concurrent data processing
* real-time candle aggregation
* order book stream handling
* websocket recovery
* latency tracking
* disconnect recovery
* message validation
* queue overflow protection
* backpressure handling
* stale stream detection
* [+] sequence number gap detection (silent data loss = arbitrage signal inversion)
* [+] checksum validation where exchange supplies it
* [+] dual-feed redundancy support (primary + backup feed)
* [+] feed-staleness watchdog (no message in N seconds → reconnect)
* [+] subscription state machine (subscribing/active/paused/failed)
* [+] message-rate metrics per stream
* [+] graceful shutdown of streams (drain buffers before exit)

Required libraries:

* asyncio
* aiohttp
* websockets
* [+] orjson (faster JSON parsing for hot path)

Architecture requirements:

* event-driven architecture
* centralized event bus
* event persistence
* queue-based processing
* producer-consumer model
* async tasks
* non-blocking pipelines
* replayable event streams
* [+] bounded queues with explicit overflow policy (drop-oldest vs block-producer)
* [+] consumer health monitoring (lag detection per consumer)
* [+] event schema versioning (so old events replay cleanly)
* [+] dead letter queue for unprocessable events
* [+] circuit breaker between producer and consumer

Event examples:

* MarketEvent
* SignalEvent
* RiskEvent
* OrderEvent
* ExecutionEvent
* PortfolioEvent
* SystemEvent
* [+] HealthEvent (component health changes)
* [+] FlagChangeEvent (feature flag toggled)
* [+] AlertEvent (kill switch, drawdown breach)
* [+] ReconciliationEvent (state sync with exchange)
* [+] PreTradeCheckEvent (compliance, risk, funds, idempotency)
* [+] FillEvent (separate from ExecutionEvent for partials)

Must explain:

* latency
* concurrency
* non-blocking systems
* event loops
* streaming reliability
* queue systems
* async design tradeoffs
* market data synchronization
* backpressure handling
* [+] sequence gap implications (silent data loss)
* [+] feed redundancy economics (cost vs reliability)
* [+] queue sizing tradeoffs (memory vs latency)

──────────────────────────────
STAGE 3 — Strategy Engine & Quantitative Logic
──────────────────────────────

Start with rule-based quantitative systems before introducing AI/ML.

Initial strategies:

* SMA crossover
* RSI mean reversion
* trend-following
* volatility breakout

Requirements:

* vectorized calculations
* reusable indicator engine
* signal generation framework
* multi-timeframe support
* dynamic strategy loading
* strategy registry system
* deterministic signal generation
* cross-timeframe synchronization
* [+] strategy versioning (semver per strategy: sma_v1.2.0)
* [+] strategy hypothesis documentation (one-pager required)
* [+] strategy execution context (clock, market regime, portfolio state)
* [+] strategy isolation (one strategy crash != system crash)
* [+] strategy timeout enforcement (signal generation < latency budget)

Example:

STRATEGIES = {
    "sma": SMAStrategy,
    "rsi": RSIStrategy
}

[+] Enhanced registry with versioning + promotion stages:
[+] STRATEGIES = {
[+]    "sma_v1.2.0": SMAStrategyV1_2_0,
[+]    "rsi_v0.3.0": RSIStrategyV0_3_0,
[+] }
[+] STRATEGY_PROMOTION_STAGE = {
[+]    "sma_v1.2.0": "live",
[+]    "rsi_v0.3.0": "shadow",
[+] }

Portfolio management requirements:

* multi-asset support
* correlation awareness
* capital allocation
* exposure balancing
* sector concentration control
* volatility balancing
* volatility targeting
* risk parity concepts
* [+] dynamic correlation matrix (rolling window)
* [+] correlation regime detection (correlations spike in crashes)
* [+] cross-asset class limits (crypto vs equity exposure caps)
* [+] currency exposure tracking (USD, USDT, USDC are not equivalent)

Risk management requirements:

* independent risk engine
* stop-loss
* take-profit
* trailing stop
* ATR-based sizing
* volatility-adjusted sizing
* daily drawdown protection
* portfolio exposure limits
* max risk per trade
* max portfolio risk
* kill conditions
* risk veto authority
* [+] fractional Kelly sizing (1/4 Kelly recommended)
* [+] volatility targeting (annualized vol target, e.g. 15%)
* [+] correlation-adjusted exposure (avoid concentration via correlated positions)
* [+] regime-aware risk multipliers (reduce sizing in high-vol regimes)
* [+] property-based testing of risk invariants (Hypothesis — MANDATORY)
* [+] risk decision audit trail (every accept/reject logged with reason)

Market regime requirements:

* trending market detection
* mean-reverting market detection
* volatility regime detection
* risk-off regime detection
* [+] regime label persistence (don't flap between regimes minute-to-minute)
* [+] regime change events broadcast on event bus
* [+] regime-conditional strategy enabling

Strategy sandbox requirements:

* signal-only mode
* shadow execution mode
* dry-run validation
* [+] paper trading mode (Alpaca Paper, Binance Testnet)
* [+] micro-live mode ($100-$1000 capital cap)
* [+] formal promotion gates between modes (see Stage 6)

Must explain:

* overfitting
* curve fitting
* survivorship bias
* look-ahead bias
* statistical robustness
* regime dependency
* strategy decay
* false edge detection
* [+] why fractional Kelly beats full Kelly in practice
* [+] why correlation regime change kills "diversified" portfolios
* [+] why promotion pipeline is mandatory (cannot skip stages)

IMPORTANT:
Avoid:

* "holy grail" systems
* unrealistic optimization
* indicator stacking
* curve fitting
* unrealistic Sharpe ratios
* [+] backtests that ignore funding rates / borrow costs
* [+] strategies without documented hypothesis
* [+] live deployment without micro-live phase

──────────────────────────────
STAGE 4 — Backtesting & Research Framework
──────────────────────────────

Implement realistic quantitative research workflows.

Backtesting period:

* 2023–2025 minimum

Requirements:

* vectorbt or backtrader
* realistic slippage
* exchange fees
* maker/taker fee modeling
* spread simulation
* partial fills
* execution delay
* liquidity modeling
* benchmark comparison
* trade analytics
* deterministic backtests
* deterministic replay engine
* [+] funding rate accrual for crypto perps
* [+] borrow cost accrual for short positions
* [+] margin call / liquidation simulation
* [+] survivorship-bias-corrected universe (delisted assets included)
* [+] point-in-time fundamental data (no restated lookahead)
* [+] realistic order book impact (size-aware slippage)
* [+] dividend / split adjustment (configurable: total return vs price return)
* [+] capacity analysis (what AUM does strategy support before alpha decay?)
* [+] research-production parity: same replay engine in tests AND backtests AND production

Required metrics:

* Sharpe Ratio
* Sortino Ratio
* Calmar Ratio
* Max Drawdown
* Win Rate
* Profit Factor
* Expectancy
* Equity Curve
* Consecutive Losses
* Exposure Time
* Recovery Factor
* Return on Capital
* [+] Tail-adjusted Sharpe (exclude top/bottom 1%)
* [+] Ulcer Index
* [+] CVaR (95%, 99%)
* [+] Maximum Adverse Excursion (MAE)
* [+] Maximum Favorable Excursion (MFE)
* [+] Implementation Shortfall (IS)
* [+] Capacity-adjusted return
* [+] Turnover and fee drag
* [+] Per-regime decomposition (return by regime label)

Validation requirements:

* walk-forward analysis
* out-of-sample testing
* parameter sensitivity testing
* Monte Carlo concepts
* replay testing
* deterministic replay testing
* [+] purged k-fold cross validation (avoid leakage)
* [+] combinatorial purged CV (Lopez de Prado method)
* [+] bootstrap confidence intervals on Sharpe
* [+] p-value calculation for strategy edge (vs random)
* [+] deflated Sharpe ratio (multiple-testing correction)
* [+] regime stratification (out-of-sample must include diverse regimes)

Research workflow:

* Jupyter notebooks
* visualization
* statistical analysis
* experiment tracking
* dataset versioning
* research environment isolation
* [+] notebooks NEVER imported by production (one-way data flow)
* [+] experiment tracking (MLflow, lightweight Stage 4)
* [+] data versioning (DVC or simple hash-based)
* [+] reproducible Jupyter kernels (papermill execution)
* [+] research → production handoff checklist

Must explain:

* why most backtests fail live
* optimization dangers
* parameter instability
* realistic expectations
* transaction cost impact
* slippage impact
* [+] why deflated Sharpe matters when testing many parameters
* [+] why combinatorial purged CV beats walk-forward for small samples
* [+] why capacity matters (your $10K backtest is not Citadel's problem)

──────────────────────────────
STAGE 5 — Execution Engine & Paper Trading
──────────────────────────────

Implement safe execution infrastructure before live deployment.

Requirements:

* Alpaca Paper Trading
* Binance Testnet
* Dry-Run Execution Mode
* simulated order execution
* market orders
* limit orders
* order tracking
* retry logic
* execution logging
* async execution engine
* transaction logging
* execution confirmation handling
* exchange reconciliation engine
* [+] idempotency keys tied to broker client_order_id
* [+] order timeout handling (cancel if not filled in N seconds)
* [+] partial fill aggregation
* [+] post-only order support (avoid taker fees)
* [+] IOC / FOK order support
* [+] iceberg order support
* [+] TWAP / VWAP execution algorithms (Stage 5b)
* [+] smart order routing across exchanges (Stage 5b, optional)
* [+] min order size / lot size / tick size validation pre-submission
* [+] order rejection classification (fixable vs unfixable)
* [+] max-orders-per-second client-side enforcement

Execution architecture:

* Signal Event
* Risk Event
* Order Event
* Execution Event
* [+] PreTradeCheck Event (compliance, risk, funds, idempotency)
* [+] OrderRoute Event (which exchange/venue chosen)
* [+] FillEvent (separate from ExecutionEvent for partials)
* [+] ReconciliationEvent (state matched with exchange)

OMS requirements:

* order lifecycle management
* pending/open/filled/cancelled states
* partial fill handling
* duplicate order prevention
* idempotent execution logic
* execution reconciliation
* [+] order state machine (formal FSM with allowed transitions)
* [+] reconciliation cadence (every minute + after every order)
* [+] orphan order detection (exchange has order, OMS doesn't, or vice versa)
* [+] order amendment support (modify quantity / price)
* [+] cancel-replace atomicity

Accounting requirements:

* realized PnL
* unrealized PnL
* fee accounting
* cash tracking
* exposure accounting
* portfolio snapshots
* [+] tax lot accounting (FIFO / LIFO / specific-ID — configurable)
* [+] wash sale rule enforcement (US equities: SPY, QQQ, SOXX)
* [+] Pattern Day Trader (PDT) rule enforcement (US, account < $25K)
* [+] long-term vs short-term capital gain tracking
* [+] currency P&L attribution (USD vs USDT vs USDC)
* [+] funding rate P&L (perps)
* [+] borrow cost P&L (shorts)
* [+] dividend / interest income tracking
* [+] daily portfolio snapshot to immutable storage

State management requirements:

* reboot recovery
* synchronize positions
* synchronize balances
* synchronize open orders
* restore system state
* periodic checkpointing
* [+] state checksum validation post-restore
* [+] state version migration (upgrade old snapshots)
* [+] state divergence alerting (OMS vs exchange mismatch)
* [+] manual reconciliation override workflow (with audit log)

[+] Compliance Subsystem (NEW SUBSECTION):

* [+] tax reporting export (CSV for accountant, format per jurisdiction)
* [+] wash sale detection and adjustment (61-day window for US equities)
* [+] PDT counter (4 day-trades in 5 rolling business days for US accounts < $25K)
* [+] regulatory holding period tracking (long-term gain qualification: > 365 days)
* [+] trade blotter export
* [+] annual 1099-B preparation aid (US)

[+] Transaction Cost Analysis (TCA) Subsystem (NEW SUBSECTION):

* [+] arrival price benchmark per execution
* [+] VWAP benchmark per execution
* [+] implementation shortfall calculation
* [+] slippage attribution: market impact vs timing vs spread
* [+] fee analysis (maker rebate captured? taker fee minimized?)
* [+] TCA dashboard per strategy (Stage 7)

[+] Trade Journal (NEW SUBSECTION):

* [+] decision rationale per signal (why did strategy emit?)
* [+] confidence level per signal
* [+] hypothesis tracking per trade
* [+] post-trade review notes
* [+] bias documentation (operator-noted)

Must explain:

* slippage
* liquidity
* order routing
* exchange behavior differences
* execution risk
* reconciliation problems
* [+] why idempotency keys matter for crash recovery
* [+] why tax lot accounting must be in-system (not in spreadsheet)
* [+] why PDT rules can shut down a strategy unexpectedly
* [+] why TCA reveals strategy decay before P&L does

──────────────────────────────
STAGE 6 — Safety Layer & Production Controls
──────────────────────────────

Implement institutional-grade safety systems.

Requirements:

* kill switch
* emergency shutdown
* max daily loss limits
* max open positions
* API failure protection
* dynamic API weight tracking
* websocket disconnect handling
* duplicate order prevention
* trade cooldown logic
* graceful shutdown logic
* persistent state saving
* restart recovery
* circuit breaker pattern
* [+] kill switch reachable via 3 redundant channels (CLI, operator UI, Telegram command)
* [+] kill switch dead-man's-switch (heartbeat lost → automatic halt)
* [+] cascading shutdown (strategy → portfolio → exchange → exit)
* [+] manual override workflow with audit log
* [+] gradual position liquidation on shutdown (avoid market impact)
* [+] safe-mode (cancel all, no new orders, monitor only)

Alerting requirements:

* Telegram alerts
* Discord alerts
* execution notifications
* error notifications
* kill switch alerts
* [+] PagerDuty / Opsgenie integration for critical alerts
* [+] alert deduplication (avoid notification storms)
* [+] alert severity classification (info / warning / critical / emergency)
* [+] runbook link in every alert message
* [+] alert acknowledgment tracking

Safety examples:

* stop trading if drawdown > 5%
* stop trading if API latency spikes
* stop trading after consecutive failures
* stop trading after abnormal volatility
* [+] stop trading if exchange clock drift > 500ms
* [+] stop trading if data feed stale > 30s
* [+] stop trading if reconciliation mismatch
* [+] stop trading if memory growth > threshold (leak indicator)
* [+] stop trading if disk free < 10%
* [+] stop trading if DB latency > threshold

[+] Strategy Promotion Subsystem (NEW SUBSECTION):

* [+] promotion stages: research → shadow (5 days) → paper (10 days) → micro-live ($100-$1000, 14 days) → live
* [+] gate criteria per stage:
    - research → shadow: hypothesis documented, code review passed
    - shadow → paper: deterministic signals for 5 days, zero crashes
    - paper → micro-live: Sharpe > target, drawdown < threshold, reconciliation 7 days clean, runbooks written
    - micro-live → live: 14 days, Sharpe > target, drawdown < threshold, zero P0/P1 bugs, post-mortems reviewed
* [+] rollback procedure: live → paper instantly via feature flag
* [+] canary deployment: 5% capital first, scale gradually (5% → 25% → 50% → 100%)
* [+] strategy retirement criteria (drawdown breach, edge decay, regime mismatch)
* [+] performance review cadence (weekly per-strategy review)
* [+] strategy hibernation (paused but not deleted)

Monitoring requirements:

* API latency monitoring
* websocket reconnect monitoring
* execution latency monitoring
* memory usage monitoring
* CPU monitoring
* [+] disk I/O monitoring (especially for tick data)
* [+] DB connection pool saturation
* [+] event bus queue depth
* [+] thread / coroutine count
* [+] file descriptor count
* [+] external API quota consumption (avoid surprise rate-limit kills)

Chaos testing requirements:

* simulate websocket failures
* simulate API outages
* simulate delayed execution
* simulate partial fills
* simulate stale data
* [+] Toxiproxy-based network chaos (latency, packet loss, disconnect)
* [+] simulate clock drift
* [+] simulate database failures
* [+] simulate exchange rejection scenarios
* [+] simulate split-brain (two instances think they're primary)
* [+] chaos schedule (randomized weekly chaos in staging)

Must explain:

* operational risk
* defensive programming
* failure scenarios
* production monitoring
* fault tolerance
* graceful degradation
* [+] why kill switch needs 3 redundant channels
* [+] why dead-man's-switch beats active monitoring
* [+] why chaos testing in staging beats fixing in prod

──────────────────────────────
STAGE 7 — Deployment & Infrastructure
──────────────────────────────

Prepare the system for long-term operation.

Requirements:

* local deployment first
* Docker support later
* VPS/cloud deployment later
* environment separation
* configurable settings
* persistent logging
* database integration
* CI-ready structure
* [+] infrastructure-as-code (Terraform / Pulumi for cloud)
* [+] Docker multi-stage build (small production image)
* [+] non-root container user
* [+] read-only root filesystem in container
* [+] secrets injected via env / Vault, never baked into image
* [+] health check endpoint (/healthz, /readyz)
* [+] graceful shutdown handling (SIGTERM → drain → exit)
* [+] log rotation policy
* [+] DB backup automation (Postgres WAL archiving, point-in-time recovery)
* [+] backup encryption + offsite copy
* [+] RPO < 1min, RTO < 5min (defined SLOs)
* [+] disaster recovery drill quarterly

Optional future upgrades:

* Redis
* Kafka
* Kubernetes
* GPU pipelines
* distributed backtesting
* [+] managed Postgres (RDS, Neon, Supabase)
* [+] managed Redis (Upstash, ElastiCache)
* [+] OpenTelemetry collector + Tempo / Jaeger backend
* [+] Grafana dashboards
* [+] Loki for log aggregation
* [+] Object storage for cold data (S3, R2)

Performance requirements:

* vectorized computations
* chunked processing
* memory-efficient DataFrames
* parallel backtesting
* future Numba optimization
* [+] memory profiling baseline (memray) before/after each release
* [+] latency regression tests in CI
* [+] benchmark suite for hot paths

[+] Disaster Recovery Subsystem (NEW SUBSECTION):

* [+] Postgres point-in-time recovery (PITR) configured
* [+] state snapshots → encrypted S3 every hour
* [+] runbook: "restore from backup" (tested quarterly)
* [+] multi-region failover plan (future)
* [+] data retention policy (raw data: forever; logs: 90 days; traces: 7 days)
* [+] secret recovery procedure (Vault unseal, key rotation)
* [+] DR drill checklist (quarterly tabletop + actual restore test)

[+] Operator Console Subsystem (NEW SUBSECTION):

* [+] manual kill switch UI (web ან Telegram)
* [+] real-time portfolio view
* [+] open orders viewer with cancel button
* [+] strategy enable/disable toggles (feature flags)
* [+] trade history viewer
* [+] alert acknowledgment UI
* [+] mobile-friendly (Telegram bot integration)
* [+] read-only operator view vs admin view (RBAC)

Must explain:

* simplicity vs complexity
* scaling gradually
* infrastructure tradeoffs
* operational maintenance
* deployment risks
* [+] why managed services beat self-hosted (DB, Redis) for small teams
* [+] why backup-without-restore-test is not a backup
* [+] why operator console is mandatory before live trading

──────────────────────────────
STAGE 8 — Future Quant & AI Expansion
──────────────────────────────

ONLY after stable infrastructure exists.

Possible future areas:

* Machine Learning
* Reinforcement Learning
* Feature engineering
* Feature store
* Regime detection
* Factor models
* Statistical arbitrage
* Sentiment analysis
* AI-assisted research agents
* [+] model registry (MLflow)
* [+] feature store (Feast or simple Postgres-based)
* [+] data versioning (DVC, LakeFS)
* [+] experiment tracking (MLflow / Weights & Biases)
* [+] A/B testing framework for ML strategies
* [+] model drift detection (PSI, KL divergence)
* [+] model retraining pipeline
* [+] champion/challenger pattern for ML strategies

IMPORTANT:
Do NOT introduce AI before:

* stable execution
* robust risk management
* reliable data
* realistic backtesting
* paper trading consistency
* deterministic research pipelines
* [+] proven rule-based baseline strategies (need a benchmark to beat)
* [+] feature pipeline that's reproducible (no notebook-only features)
* [+] latency budget that accommodates inference

Emphasize:
"Infrastructure and risk management are more important than strategy complexity."
"AI without infrastructure is gambling with extra steps."

──────────────────────────────
TESTING REQUIREMENTS
──────────────────────────────

Implement:

* unit tests
* integration tests
* replay tests
* regression tests
* simulation tests
* chaos testing
* [+] property-based testing (Hypothesis) — MANDATORY for risk engine, position sizing, parsers
* [+] mutation testing (mutmut) — verify test quality
* [+] contract tests (schemathesis) — verify exchange API assumptions
* [+] snapshot tests (DataFrame outputs)
* [+] load tests (Locust) — concurrent order submission
* [+] fuzz tests — market data parsers
* [+] latency tests — assert per-stage budgets

Testing must cover:

* strategy logic
* execution engine
* websocket recovery
* OMS behavior
* portfolio accounting
* risk engine
* [+] tax lot accounting (especially wash sale)
* [+] PDT rule enforcement
* [+] idempotency under concurrent submission
* [+] reconciliation under exchange mismatch
* [+] kill switch under various failure modes
* [+] config loading / validation
* [+] migration up/down

Must explain:

* why testing matters in trading systems
* replay testing
* regression prevention
* deterministic testing
* [+] why property-based testing finds bugs deterministic tests miss
* [+] why mutation testing reveals fake coverage
* [+] why contract tests prevent silent exchange API changes
* [+] why coverage % is necessary but not sufficient

──────────────────────────────
OBSERVABILITY & MONITORING
──────────────────────────────

Implement:

* structured logging
* metrics collection
* execution telemetry
* reconnect counters
* latency metrics
* strategy diagnostics
* system health monitoring
* audit trail logging
* [+] OpenTelemetry distributed tracing (signal-to-fill spans)
* [+] correlation IDs across all logs
* [+] trace sampling policy (100% orders, 10% data fetch)
* [+] log aggregation (Loki / ELK)
* [+] metric dashboards (Grafana)
* [+] SLO definitions (latency p99, error rate, freshness)
* [+] error budget tracking
* [+] runbook URL in every error log

Metrics examples:

* API latency
* execution latency
* websocket reconnect count
* strategy runtime
* memory usage
* CPU usage
* [+] order submit-to-ack latency p50/p95/p99
* [+] signal-to-fill latency p50/p95/p99
* [+] data feed staleness gauge
* [+] reconciliation drift gauge
* [+] feature flag evaluations counter
* [+] idempotency cache hit ratio
* [+] DB connection pool utilization
* [+] event bus queue depth per consumer
* [+] strategy P&L (realtime gauge)
* [+] daily drawdown gauge

──────────────────────────────
TIME SYNCHRONIZATION
──────────────────────────────

Implement:

* [+] exchange server time validation
* [+] clock drift detection
* [+] timestamp consistency checks
* [+] trading session synchronization
* [+] NTP / chrony daemon configuration (production: drift < 5ms)
* [+] PTP (Precision Time Protocol) for ultra-low-latency (future, optional)
* [+] UTC enforcement throughout codebase (no naive datetimes)
* [+] timezone-aware datetimes via Pandera schema validation
* [+] DST handling for ETF sessions
* [+] alert if drift > 100ms, halt if drift > 500ms

Must explain:

* [+] why time synchronization matters
* [+] clock drift risks
* [+] exchange timestamp inconsistencies
* [+] why naive datetimes are a category of bug
* [+] why drift > 500ms can cause arbitrage signals to invert

──────────────────────────────
MARKET SESSION MANAGEMENT
──────────────────────────────

Implement:

* [+] NYSE/NASDAQ trading sessions (via pandas_market_calendars)
* [+] market holidays
* [+] half-day sessions
* [+] pre-market/post-market handling
* [+] crypto 24/7 session handling
* [+] earnings blackout windows (configurable per symbol)
* [+] Fed announcement blackout windows (optional)
* [+] crypto network maintenance windows (Binance scheduled downtime)
* [+] daylight saving transition handling

Must explain:

* [+] ETF session differences
* [+] session-based execution risks
* [+] overnight gap risks
* [+] why pre-market liquidity is dangerous for retail
* [+] why crypto "24/7" is a lie (exchanges have maintenance, network has congestion)

──────────────────────────────
AUDITABILITY & REPLAYABILITY
──────────────────────────────

Implement:

* full audit trail
* strategy decision traceability
* order decision traceability
* deterministic replay engine
* execution replay support
* [+] append-only audit log table (Postgres) with WORM retention policy
* [+] event log captures: actor, action, payload, correlation_id, timestamp, prev_event_id, hash
* [+] event hash chaining (tamper detection)
* [+] decision rationale logging (why did strategy emit signal?)
* [+] risk decision logging (why did risk veto?)
* [+] config snapshot per event (what config was active?)
* [+] strategy version per event
* [+] replay produces bit-identical outputs (deterministic seeds)

Must explain:

* why auditability matters
* debugging production systems
* replay-driven debugging
* [+] why event hash chaining catches log tampering
* [+] why config snapshots matter (can't replay if config changed)
* [+] why deterministic replay is the foundation of trustable backtests

──────────────────────────────
[+] SECURITY ARCHITECTURE (NEW SECTION)
──────────────────────────────

Implement:

* [+] secret management hierarchy (.env dev → Vault prod)
* [+] API key segregation (read-only / trade-only / withdraw-enabled — 3 separate keys)
* [+] withdrawal whitelist on exchange side (CRITICAL — most important security control)
* [+] IP whitelist on exchange side
* [+] 90-day API key rotation policy
* [+] 2FA enforcement on all related accounts
* [+] pre-commit secret scanning (detect-secrets)
* [+] CI secret scanning (gitleaks history scan)
* [+] dependency scanning (pip-audit) in CI
* [+] SAST scanning (bandit) in CI
* [+] container scanning (Trivy) in CI when Docker added
* [+] HTTPS / TLS for all external connections
* [+] certificate pinning for exchange APIs (optional)
* [+] audit log immutability (append-only, hash-chained)
* [+] principle of least privilege (DB users, OS users)
* [+] hot/cold wallet separation logic (crypto)
* [+] documented incident response procedure (key leak, breach)

Must explain:

* [+] why withdrawal whitelist is the most important security control
* [+] why .env in production is unacceptable
* [+] why API key rotation is hygiene, not paranoia
* [+] why three-key segregation limits blast radius

──────────────────────────────
[+] COST MANAGEMENT (NEW SECTION)
──────────────────────────────

Implement:

* [+] Transaction Cost Analysis (TCA) per strategy
* [+] infrastructure cost tracking (cloud bills, exchange fees)
* [+] API call cost tracking (some data is per-request priced)
* [+] market data subscription cost tracking
* [+] compute cost per backtest (avoid runaway research)
* [+] cost budget alerts (monthly threshold)

Must explain:

* [+] why TCA is the second-best leading indicator of strategy decay (after Sharpe)
* [+] why infrastructure costs can exceed alpha for small accounts

──────────────────────────────
[+] DATA QUALITY & LINEAGE (NEW SECTION)
──────────────────────────────

Implement:

* [+] data lineage metadata (source → transformation → sink)
* [+] data quality SLOs (completeness, freshness, accuracy)
* [+] freshness watchdog (alert if data > 2× expected interval old)
* [+] cross-source price validation (Binance vs Coinbase)
* [+] tick anomaly detection (z-score)
* [+] schema evolution tracking
* [+] data quarantine (bad data isolated, not deleted — for audit)

Must explain:

* [+] why bad data silently corrupts strategy outputs
* [+] why cross-source validation catches exchange-specific bugs
* [+] why data quarantine beats data deletion (for audit)

──────────────────────────────
[+] DOCUMENTATION ENGINEERING (NEW SECTION)
──────────────────────────────

Implement:

* [+] Architecture Decision Records (ADRs) — every significant decision
* [+] Runbooks per incident type (websocket disconnect, API outage, kill switch fired, reconciliation mismatch)
* [+] Strategy one-pagers (hypothesis, edge, regime, risks, owner)
* [+] Post-mortem template (blameless, timeline, contributing factors, action items)
* [+] On-call rotation policy + escalation policy
* [+] CHANGELOG.md (Keep-a-Changelog format)
* [+] Semantic versioning for the system itself
* [+] CLAUDE.md / AGENTS.md (Claude Code instructions per repo)
* [+] README.md with quickstart, architecture overview, glossary

Must explain:

* [+] why ADRs prevent decision-decay
* [+] why blameless post-mortems beat blame-storms
* [+] why runbooks are written before incidents, not after

──────────────────────────────
[+] STRATEGY LIFECYCLE MANAGEMENT (NEW SECTION)
──────────────────────────────

Implement:

* [+] strategy versioning (semver)
* [+] strategy registry with metadata (owner, hypothesis, promotion stage)
* [+] promotion pipeline: research → shadow → paper → micro-live → live
* [+] promotion gates: minimum days, minimum trades, max drawdown, code review
* [+] canary deployment (5% capital first, scale)
* [+] rollback via feature flag (instant live → paper)
* [+] retirement criteria (drawdown breach, edge decay, regime mismatch)
* [+] weekly performance review meetings
* [+] strategy hibernation (paused but not deleted)

──────────────────────────────
[+] OPERATIONAL READINESS CHECKLIST (NEW SECTION)
──────────────────────────────

Before promoting from paper to micro-live:

* [+] kill switch tested in chaos environment (3-channel + dead-man's switch verified)
* [+] runbook written for top 5 failure modes
* [+] backup and restore tested end-to-end
* [+] alerts firing correctly to operator phone
* [+] reconciliation verified clean for 7 consecutive days
* [+] zero P0/P1 bugs in last 14 days
* [+] config diff from paper logged and reviewed
* [+] capital cap enforced ($100-$1000)
* [+] withdrawal whitelist verified on exchange
* [+] IP whitelist verified on exchange
* [+] secrets rotated and verified
* [+] tax lot tracking verified accurate

Before promoting from micro-live to live:

* [+] minimum 14 days at micro-live
* [+] Sharpe > target threshold
* [+] drawdown < threshold
* [+] zero reconciliation issues
* [+] zero P0/P1 bugs
* [+] post-mortem reviewed for any incidents
* [+] capital scaling plan defined (5% → 25% → 50% → 100%)
* [+] DR drill passed in last quarter

──────────────────────────────
NON-GOALS
──────────────────────────────

The system is NOT initially intended for:

* High-Frequency Trading (HFT)
* colocated ultra-low-latency systems
* leveraged futures trading
* options market making
* fully autonomous AI trading
* high-risk martingale systems
* [+] options Greeks management (no options strategies)
* [+] cross-margin / portfolio margin (single-margin only)
* [+] regulatory broker-dealer functionality
* [+] customer-facing API (single-operator only)
* [+] multi-tenant operation
* [+] tokenized asset issuance
* [+] DeFi smart contract interaction (Stage 0-7)

──────────────────────────────
CODING REQUIREMENTS
──────────────────────────────

All code must follow:

* modular architecture
* clean code principles
* SOLID principles
* type hints
* docstrings
* structured logging
* exception handling
* configuration-driven design
* [+] Conventional Commits (commitlint enforced)
* [+] semantic versioning (CHANGELOG.md updated per release)
* [+] mypy --strict mode
* [+] ruff lint + format (CI gate)
* [+] no print() in production code (structlog only)
* [+] no bare except (always except SpecificException)
* [+] no mutable default arguments
* [+] async-only at I/O boundaries (CPU-bound work in executor)
* [+] no global state (use dependency injection)
* [+] Big-O documented for critical hot paths

Every implementation must include:

* explanation in Georgian
* file placement
* execution instructions
* dependency installation commands
* debugging guidance
* [+] ADR reference (if architectural)
* [+] runbook reference (if operational)
* [+] test plan
* [+] rollback plan

Whenever possible:

* prefer vectorized operations
* avoid unnecessary loops
* use async architecture
* design for scalability
* optimize memory usage
* [+] benchmark hot paths (memray, py-spy)
* [+] profile before optimizing (no premature optimization)

Always explain:

* WHY the implementation is designed this way
* architectural tradeoffs
* production implications
* real-world quant engineering practices
* [+] alternatives considered (with rejection rationale)
* [+] cost implications (where relevant)
* [+] security implications (where relevant)
* [+] failure modes and recovery

NEVER:

* build unrealistic "get rich quick" systems
* optimize irresponsibly
* ignore risk management
* overfit historical data
* deploy directly to live trading
* hide engineering tradeoffs
* [+] commit secrets to git
* [+] log raw API keys, tokens, or PII
* [+] skip the promotion pipeline
* [+] disable risk engine in live mode
* [+] amend public commits
* [+] use --no-verify on git commits
* [+] mix research code into production package
* [+] use mutable global state
* [+] catch and silently ignore exceptions

──────────────────────────────
[+] OPEN DECISIONS REQUIRING USER CONFIRMATION (NEW SECTION)
──────────────────────────────

Before implementation begins, the following decisions need user input:

1. Repo location: new repo at ~/trading-bot/ vs subfolder of wishmotors-tg-analyzer
   Recommendation: NEW REPO

2. Database strategy: Postgres only vs Postgres + DuckDB/Parquet
   Recommendation: Postgres + DuckDB/Parquet (OLTP/OLAP separation)

3. Initial exchange: Binance only vs Binance + Alpaca + yfinance
   Recommendation: All three abstractions, Binance first concrete impl

4. Memory profiler: memray vs memory_profiler
   Recommendation: memray (Apple Silicon optimized)

5. Event bus: asyncio.Queue vs Redis Streams
   Recommendation: asyncio.Queue Stage 0/1, Redis Streams Stage 2+

6. Tracing backend (local): Jaeger vs Tempo vs Console
   Recommendation: Console for dev, Jaeger for production

7. Python version: 3.12 vs 3.13
   Recommendation: 3.12 (3.13 still new for some libs)

8. Promotion pipeline rigor: strict gates vs flexible thresholds
   Recommendation: strict gates (research → shadow → paper → micro-live → live)

9. Secrets manager (production): Vault vs AWS Secrets Manager vs Doppler
   Recommendation: Vault (open source, self-hostable, broad ecosystem)

10. Cache format Stage 1: CSV vs Parquet
    Recommendation: Parquet (typed, compressed, faster)

──────────────────────────────
FIRST TASK
──────────────────────────────

Start with STAGE 0 and STAGE 1.

Create:

1. complete project structure
2. pyproject.toml + uv.lock + requirements-dev.txt
3. .env example
4. hierarchical config system (pydantic-settings + YAML, with versioning)
5. structured logging setup (structlog JSON, correlation IDs)
6. exchange abstraction layer (Pydantic DTOs)
7. data provider abstraction layer (Pydantic DTOs)
8. secure CCXT connection (read-only key)
9. historical BTC/USDT OHLCV downloader (Parquet, partitioned, idempotent, resumable)
10. Pandas DataFrame processing with Pandera schema validation
11. 50 SMA calculation
12. local Parquet caching
13. APScheduler job example (persistent, retrying)
14. startup environment validation (verify_environment.py)
15. centralized rate limiter example (token bucket per exchange)
16. feature flag example (DB-backed with cache, decorator-based)
17. basic pytest example
18. audit logging example (append-only, hash-chained)
19. explanation of every component in Georgian
20. [+] OpenTelemetry tracing setup (console exporter for dev)
21. [+] Prometheus metrics endpoint
22. [+] idempotency key store (UUID v7, Postgres-backed) + decorator
23. [+] time sync utility (exchange clock check, NTP comparison)
24. [+] pre-commit configuration (ruff, mypy, detect-secrets, large-file)
25. [+] ADR template + initial 8 ADRs
26. [+] CI pipeline (.github/workflows/ci.yml — lint, typecheck, test, security, migrations)
27. [+] Property-based test example (Hypothesis on risk invariants)
28. [+] Replay test fixture format example
29. [+] CLAUDE.md repo-specific instructions
30. [+] README.md + CHANGELOG.md
31. [+] alembic initial migration (audit_log, feature_flags, idempotency_keys, ohlcv tables)
32. [+] runbook template + first runbook (websocket-disconnect.md)
33. [+] post-mortem template
34. [+] graceful shutdown handler (SIGTERM → drain → exit)
35. [+] data quality monitor (freshness, anomaly detection)

Then explain step-by-step:

* how to run everything in VS Code on Apple Silicon M4
* how to debug the system
* how to validate API connectivity
* how to verify data integrity
* how to extend the architecture safely
* how to replay historical datasets deterministically
* [+] how to add a new ADR
* [+] how to write a runbook
* [+] how to use OpenTelemetry traces for debugging
* [+] how to interpret Prometheus metrics
* [+] how to use idempotency keys correctly
* [+] how to test for time-related bugs
* [+] how to promote a strategy through pipeline stages
* [+] how to handle a security incident (key leak, breach)

──────────────────────────────
[+] CAPITAL MANAGEMENT & OPERATIONAL LIMITS TIERING (NEW SECTION — v4)
──────────────────────────────

Implement:

* [+] Drawdown circuit breaker tiers:
    - Tier 1 (5% daily DD): pause new positions, allow exits only
    - Tier 2 (10% daily DD): full halt, manual intervention required
    - Tier 3 (15% daily DD): emergency liquidation + multi-channel alert
* [+] Per-strategy capital limits (configurable in YAML)
* [+] Per-symbol concentration limits (max % of portfolio in single asset)
* [+] Daily / weekly / monthly loss limits (cumulative drawdown caps)
* [+] Maximum daily turnover limit (avoid excessive churn)
* [+] Cool-down periods after stop-loss hit (no re-entry for N hours)
* [+] Per-strategy maximum order size (capital × allocation × max_leverage)
* [+] Capital allocation rebalancing cadence (weekly with audit log)
* [+] Reserved capital floor (always keep 10% in cash for opportunity)
* [+] Portfolio leverage cap (1× spot, future: configurable for derivatives)

Must explain:

* [+] why tiered drawdown beats binary kill switch (graceful degradation)
* [+] why concentration limits matter even in "diversified" portfolios
* [+] why cool-down beats immediate re-entry after stop-loss

──────────────────────────────
[+] RECONCILIATION EDGE CASES (NEW SECTION — v4)
──────────────────────────────

Implement handlers for:

* [+] partial fills during reconnection (resume tracking on reconnect)
* [+] orders placed during exchange disconnection (rejected? queued?)
* [+] stale order cleanup (orders pending > 24h → flag for review)
* [+] phantom positions detection (exchange has, OMS doesn't)
* [+] orphan positions detection (OMS has, exchange doesn't)
* [+] currency conversion mid-trade (USDT → USDC settlement edge case)
* [+] funding rate accrual during disconnection (perps)
* [+] dividend payment during disconnection (equities)
* [+] split/merger event during open position
* [+] exchange unilateral order cancellation (e.g. risk-engine cancellation by exchange)
* [+] balance discrepancy alerting (OMS balance ≠ exchange balance > tolerance)
* [+] manual reconciliation override workflow (with audit log + dual-approval)

Must explain:

* [+] why reconciliation must run on schedule, not just on-demand
* [+] why phantom orders can compound (one ghost = duplicate fills downstream)
* [+] why manual override needs dual-approval

──────────────────────────────
[+] STRATEGY RESEARCH HYGIENE (NEW SECTION — v4)
──────────────────────────────

Implement:

* [+] pre-registered hypothesis registry (state hypothesis BEFORE testing — avoid p-hacking)
* [+] negative result archive (failed strategies archived in `docs/strategies/archived/` not deleted)
* [+] statistical power analysis before testing (minimum sample size calculation)
* [+] multi-strategy correlation tracking (avoid disguised duplicate strategies)
* [+] Bonferroni / Holm-Bonferroni / FDR correction for multiple comparisons
* [+] research notebook template (hypothesis, data, method, results, decision)
* [+] research peer review (second pair of eyes before promotion)
* [+] reproducibility checklist (random seeds, library versions, data versions)
* [+] strategy ablation studies (which component contributes most to edge?)
* [+] parameter sensitivity heat-maps (visualize parameter stability)

Must explain:

* [+] why pre-registration prevents p-hacking
* [+] why negative results are valuable (avoid retesting bad ideas)
* [+] why multi-comparison correction matters at scale

──────────────────────────────
[+] RESILIENCE PATTERNS (NEW SECTION — v4)
──────────────────────────────

Implement architectural patterns:

* [+] **Bulkhead pattern**: isolate failures per asset/strategy (one strategy crash != system crash)
* [+] **Saga pattern**: multi-step operations with compensating actions (e.g. cross-exchange transfer)
* [+] **Retry budget**: max 100 retries per minute system-wide (avoid retry storms)
* [+] **Hedged requests**: race two data providers, take fastest response (Stage 7+)
* [+] **Circuit breaker**: open/half-open/closed states, configurable thresholds
* [+] **Backpressure feedback**: downstream slowness propagates upstream (slow consumer signals producer)
* [+] **Timeout cascades**: parent timeout > child timeout (no orphaned operations)
* [+] **Idempotent operations**: every retryable operation must be idempotent
* [+] **Graceful degradation modes**: full operation → reduced operation → safe-mode → halt
* [+] **Cellular architecture**: future scaling to multiple isolated trading cells

Must explain:

* [+] why bulkhead prevents one bad strategy from killing the system
* [+] why retry budgets prevent self-DDoS
* [+] why saga is needed for multi-step operations that can partially fail

──────────────────────────────
[+] SYNTHETIC TRANSACTIONS & CANARY TRADES (NEW SECTION — v4)
──────────────────────────────

Implement:

* [+] **Canary trade per market-open**: smallest possible order ($1 BTC, 1 share SPY) to verify execution path end-to-end
* [+] **End-to-end latency probes**: synthetic signals through full pipeline, measure p99 latency
* [+] **Synthetic webhook injections**: test alerting paths without real incidents
* [+] **Health check that exercises full pipeline**: not just "DB up?" but "can we place a paper order?"
* [+] **Continuous reconciliation probes**: periodic small queries to verify exchange connectivity + auth
* [+] **Canary trade alerting**: if canary fails → halt trading + page operator
* [+] **Probe metrics in Prometheus**: probe_success_rate, probe_latency_seconds

Must explain:

* [+] why "DB ping" health checks miss real issues
* [+] why canary trades catch issues before strategies notice
* [+] why probes must run continuously, not just at startup

──────────────────────────────
[+] ADVERSARIAL & MARKET MICROSTRUCTURE CONSIDERATIONS (NEW SECTION — v4)
──────────────────────────────

Implement:

* [+] **Front-running protection**: don't signal intent — randomize order timing within tolerance window
* [+] **MEV protection on crypto**: 
    - private mempools (Flashbots Protect, MEV Blocker)
    - anti-sandwich attack protection
    - private RPC endpoints
* [+] **Wash trading detection**: avoid mistaking exchange wash trades as real volume
* [+] **Spoofing/layering detection in order book data**: filter manipulation noise
* [+] **Pump-and-dump detection**: avoid trading thinly-traded assets during anomalous volume
* [+] **Stop-hunting awareness**: don't place stops at obvious round numbers
* [+] **Order size obfuscation**: split large orders into smaller chunks (TWAP/iceberg)
* [+] **Time-of-day risk**: avoid trading during low-liquidity windows (off-hours, holidays)

Must explain:

* [+] why predictable execution patterns can be exploited
* [+] why MEV is real money loss on crypto
* [+] why wash trading distorts volume-based signals

──────────────────────────────
[+] COUNTRY-SPECIFIC TAX — GEORGIA (NEW SECTION — v4)
──────────────────────────────

Implement:

* [+] **საქართველოს tax რეჟიმი crypto trading-ისთვის:**
    - 2023 წელს მიღებული რეგულაცია: ფიზიკური პირისთვის crypto-ს მოგება გათავისუფლებული საშემოსავლო გადასახადისგან (`სსგ მუხ. 82, ნაწ. 1, გ²`)
    - Resident vs non-resident classification
    - Source-of-income rules
* [+] **VAT considerations:**
    - კრიპტოვალუტის გაცვლა — გათავისუფლებული VAT-ისგან
    - მონეტიზებული ფინანსური ოპერაციები
* [+] **Personal income tax structure:**
    - 20% flat rate (default)
    - 5% Small Business Status (თუ qualifying)
    - 1% Individual Entrepreneur Status (turnover < 500K GEL)
* [+] **Reporting requirements (განცხადება):**
    - წლიური საშემოსავლო გადასახადის დეკლარაცია (საჭიროა?)
    - Foreign-source income reporting
    - Crypto wallet disclosure (TBD per regulator)
* [+] **Equity trading (SPY, QQQ, SOXX):**
    - Foreign-source income — 20% on capital gains (resident)
    - Tax treaty considerations (Georgia-USA)
    - Withholding on dividends (US: 30% default, 10% with treaty)
* [+] **Trading bot accounting outputs:**
    - GEL-denominated annual report
    - Per-asset cost basis report
    - Crypto-specific report (separate due to different tax treatment)
* [+] **Disclaimer:** ეს სპეციფიკაცია არ არის ფინანსური / სამართლებრივი რჩევა — გადაამოწმეთ ლიცენზირებულ tax advisor-თან.

Must explain:

* [+] რატომ უნდა იყოს tax export-ი jurisdiction-aware
* [+] რატომ ცალკე უნდა იყოს crypto vs equity tax reporting
* [+] რატომ მნიშვნელოვანია source-of-income tracking ქართველი resident-ისთვის

──────────────────────────────
[+] QUALITY GATES SPECIFICS (NEW SECTION — v4)
──────────────────────────────

Implement:

* [+] **PR review checklist (mandatory):**
    - tests added/updated for changed code
    - ADR linked if architectural change
    - runbook updated if operational change
    - CHANGELOG.md entry added
    - mypy --strict passes
    - ruff check + format passes
    - pip-audit / bandit shows no new criticals
    - documented rollback procedure
* [+] **Required CI checks (cannot merge without):**
    - lint (ruff)
    - typecheck (mypy --strict)
    - unit tests (≥85% coverage)
    - integration tests
    - property tests (Hypothesis)
    - security scan (pip-audit, bandit, detect-secrets)
    - migration up/down tests
    - replay regression tests
* [+] **Code coverage gates per module:**
    - risk engine: ≥95%
    - OMS: ≥95%
    - accounting: ≥95%
    - strategies: ≥85%
    - utils: ≥85%
    - infrastructure: ≥75%
* [+] **Performance budget gates:**
    - latency regression > 10% on hot path → fail PR
    - memory regression > 20% → fail PR
    - benchmark suite runs on every PR
* [+] **Security review gate:**
    - mandatory for: secret handling, auth code, exchange API integration, withdrawal logic
    - sign-off from security reviewer required
* [+] **Branch protection rules:**
    - main is protected
    - require PR before merge
    - require status checks
    - require linear history (rebase, no merge commits)
    - dismiss stale reviews on new commits

Must explain:

* [+] რატომ უნდა იყოს per-module coverage gates (risk engine deserves higher bar)
* [+] რატომ მნიშვნელოვანია performance gates in CI (latency regression silently kills strategies)

──────────────────────────────
[+] EXTERNAL DEPENDENCIES RISK MANAGEMENT (NEW SECTION — v4)
──────────────────────────────

Implement:

* [+] **Vendor lock-in analysis:**
    - CCXT — what if abandoned? Migration cost estimate
    - Alpaca — what if pricing changes? Alternative brokers (IBKR, TastyTrade)
    - Binance — what if regional restrictions? Backup exchange (Coinbase, Kraken)
    - yfinance — what if Yahoo blocks? Backup (Polygon.io, Tiingo)
* [+] **Failover providers per data source:**
    - Primary + secondary + tertiary defined per data type
    - Automatic failover on primary failure
    - Reconciliation across providers
* [+] **SLA tracking per dependency:**
    - exchange uptime tracking
    - API latency SLO
    - data freshness SLO
* [+] **Dependency renewal calendar:**
    - SSL certs
    - API key rotation dates
    - Subscription renewals
    - License expiries
* [+] **Open-source dependency health:**
    - last commit date (red if > 1 year)
    - maintainer count (red if = 1)
    - known critical CVEs
    - license compatibility
    - alternative if abandoned
* [+] **Dependency-pinning strategy:**
    - exact version pins in production
    - Renovate / Dependabot for automated PRs
    - security patches fast-tracked

Must explain:

* [+] რატომ vendor lock-in = strategic risk
* [+] რატომ pinned dependencies > floating ranges in production
* [+] რატომ open-source health audit ყოველ კვარტალში

──────────────────────────────
[+] TIME-BASED SPECIAL WINDOWS (NEW SECTION — v4)
──────────────────────────────

Implement:

* [+] **FOMC announcement windows:**
    - no new positions 30 min before / 30 min after
    - widen stops during announcement
    - configurable per strategy (some thrive on volatility)
* [+] **Earnings blackout per symbol:**
    - 1 day before / 1 day after earnings (configurable)
    - earnings calendar fetched from authoritative source
* [+] **End-of-quarter rebalancing volatility:**
    - last week of March/June/Sep/Dec — institutional rebalancing
    - widen risk parameters
* [+] **Holiday-eve liquidity drops:**
    - day before US holidays — reduced volume
    - reduce position sizes
* [+] **Year-end tax loss harvesting windows:**
    - December — increased volatility from tax harvesting
    - January effect monitoring
* [+] **Crypto halving events:**
    - BTC halving every ~4 years (next: 2028)
    - increased volatility window: ±30 days
    - enhanced risk monitoring during these windows
* [+] **Triple witching:**
    - third Friday of March/June/Sep/Dec
    - options + futures + index options expire simultaneously
    - elevated volatility
* [+] **Market open / close windows:**
    - first 15 min: high spread, low liquidity → caution
    - last 15 min: high volume, MOC orders → caution

Must explain:

* [+] რატომ time-based windows არ არის optional safety
* [+] რატომ events calendar უნდა იყოს first-class data source

──────────────────────────────
[+] PERFORMANCE ENGINEERING (NEW SECTION — v4)
──────────────────────────────

Implement:

* [+] **Hot path identification:**
    - profile with py-spy / memray every release
    - 90% of CPU time should be identified and named
    - flame graphs archived per release
* [+] **Pre-computed indicators:**
    - SMA / RSI / etc. computed once per candle, cached
    - avoid recalculation per tick
    - invalidation strategy: time-based + dependency-based
* [+] **Async batching:**
    - DB writes batched (commit every 100 events or 1 second)
    - log writes batched
    - metric updates batched
* [+] **Database query patterns:**
    - avoid N+1 queries (use joins or batch fetches)
    - use prepared statements (asyncpg auto-prepares)
    - connection pool sized to expected concurrency
    - read replicas for analytics (Stage 7+)
* [+] **Connection pool sizing per dependency:**
    - DB: 10-20 connections (main + read replicas)
    - exchange API: respect rate limit (1-3 connections)
    - Redis: 5-10 connections
* [+] **Memory management:**
    - DataFrame chunking for large datasets
    - streaming where possible (avoid loading full history)
    - explicit GC hints for long-running processes
* [+] **Latency budgets per stage (CI-asserted):**
    - data ingestion: < 50ms
    - signal generation: < 100ms
    - risk check: < 20ms
    - order submission: < 200ms
    - end-to-end signal-to-fill: < 500ms p99
* [+] **Vectorization audit:**
    - any Python loop in hot path = code review red flag
    - prefer numpy / pandas vectorized ops
    - Numba JIT for compute-bound hotspots (Stage 7+)

Must explain:

* [+] რატომ profile before optimize (premature optimization)
* [+] რატომ latency budgets > average latency targets
* [+] რატომ N+1 queries silently kill performance

──────────────────────────────
[+] KNOWLEDGE MANAGEMENT (NEW SECTION — v4)
──────────────────────────────

Implement:

* [+] **Strategy notebook (lessons learned per strategy):**
    - what worked
    - what didn't
    - what surprised us
    - changes over time
    - retirement notes
* [+] **Trading psychology log (operator notes):**
    - emotional state at decision points
    - decision triggers
    - bias patterns observed
    - intervention rules ("if I feel X, then Y")
* [+] **Bug bash days (scheduled):**
    - quarterly fault-injection days
    - whole team finds + fixes bugs in staging
    - new failure modes added to chaos catalog
* [+] **Technical debt register (TD register):**
    - tracked debt items with severity + paydown estimate
    - 20% of sprint capacity reserved for paydown
    - debt accruing alerts (debt grows N% / month)
* [+] **Architecture review cadence:**
    - quarterly architecture review meeting
    - ADRs reviewed for relevance (still accepted? superseded?)
    - new ADRs ratified
* [+] **Glossary (in README.md or docs/glossary.md):**
    - domain-specific terms defined
    - acronyms expanded
    - new team members onboard from glossary
* [+] **Onboarding checklist:**
    - access setup (DB, exchange testnet, monitoring dashboards)
    - documentation reading list (ADRs, runbooks, README)
    - first-week tasks
* [+] **Decision log (separate from ADRs):**
    - smaller decisions that don't warrant ADR
    - searchable history of "why we did X"

Must explain:

* [+] რატომ knowledge documentation prevents brain drain
* [+] რატომ technical debt must be measured, not just felt

──────────────────────────────
[+] CHAOS ENGINEERING SPECIFICS (EXPANSION OF STAGE 6 — v4)
──────────────────────────────

Specific failure scenarios catalog (chaos catalog):

* [+] **Network failures:**
    - exchange returns 500 for 30 seconds
    - exchange returns 429 (rate limit) repeatedly
    - DNS resolution fails for exchange domain
    - TCP connection drops mid-request
    - TLS handshake hangs
    - websocket disconnects every 60 seconds
    - websocket sends garbage data
* [+] **Database failures:**
    - DB latency suddenly 10× higher
    - DB connection pool exhausted
    - DB deadlock on hot row
    - DB read replica lag > 30 seconds
    - DB primary fails over
    - DB disk full
* [+] **Resource exhaustion:**
    - memory pressure simulation (90% RAM used)
    - disk full simulation
    - file descriptor exhaustion
    - thread/coroutine pool exhausted
* [+] **Time-related:**
    - clock jumps backward 5 minutes
    - clock jumps forward 5 minutes
    - NTP sync fails
    - exchange time drifts > 1 second
* [+] **Coordination failures:**
    - two instances accidentally start (split-brain)
    - leader election fails
    - distributed lock not released
* [+] **Data corruption:**
    - malformed JSON from exchange
    - duplicate messages in stream
    - out-of-order messages
    - sequence gap in stream
    - tick with negative price
    - tick with zero volume + non-zero price
* [+] **Authentication failures:**
    - API key expired mid-request
    - API key revoked
    - 2FA challenge unexpected
    - IP whitelist violation

Implement:

* [+] **Game day exercises:**
    - planned tabletop exercises monthly
    - random chaos injection in staging weekly
    - quarterly full-system chaos drill
* [+] **Chaos as code:**
    - Toxiproxy configurations versioned in git
    - chaos scenarios documented with expected behavior
    - automated chaos test suite in CI (light scenarios)
* [+] **Chaos metrics:**
    - mean time to detect (MTTD)
    - mean time to recover (MTTR)
    - blast radius per scenario
    - cascading failure detection

Must explain:

* [+] რატომ chaos engineering > faith-based reliability
* [+] რატომ chaos catalog must grow with every incident

──────────────────────────────
[+] CONFIGURATION DRIFT & SCHEMA MIGRATION (NEW SECTION — v4)
──────────────────────────────

Implement:

* [+] **Configuration drift detection:**
    - prod config vs declared config (in git) compared on startup
    - drift = alert + audit log entry
    - manual override audit trail
* [+] **Configuration testing:**
    - lint test for valid YAML syntax
    - schema validation for config types
    - cross-config consistency checks (e.g. strategy references existing exchange)
    - test in CI with sample configs per environment
* [+] **Schema migration of stored events:**
    - event schema versioned (v1, v2, v3)
    - upgrade function per version transition
    - replay engine handles all versions
    - retention: keep upgraders for last N versions
* [+] **Backward compatibility windows:**
    - new event schema must support reading old events for N days
    - deprecation warnings logged
    - migration date scheduled and announced
* [+] **Configuration as code:**
    - all config changes via PR
    - reviewer required
    - CI runs config validation
    - rollback via git revert
* [+] **Secret rotation without downtime:**
    - dual-key support during rotation
    - graceful key switchover
    - rotation testing in staging
* [+] **Configuration audit log:**
    - who changed what config when
    - configuration snapshots per release
    - searchable history

Must explain:

* [+] რატომ config drift = silent production bugs
* [+] რატომ event schema versioning enables long-term replay
* [+] რატომ secrets rotation must be tested before being needed

──────────────────────────────
[+] STRESS TESTING & HISTORICAL SCENARIO REPLAY (NEW SECTION — v5)
──────────────────────────────

Implement:

* [+] **Historical scenario replay catalog:**
    - 2008 GFC (October 2008 — equities -30%)
    - 2020 March (COVID crash — equities -34% in 33 days)
    - 2020 March (BTC -50% in 24h)
    - 2022 May (Terra/LUNA collapse)
    - 2022 November (FTX collapse — 18% BTC drop, exchange counterparty failure)
    - 2024 August (yen carry trade unwind)
* [+] **Hypothetical scenario stress tests:**
    - Equity flash crash: -10% in 1 hour
    - Crypto flash crash: -30% in 1 hour
    - Stablecoin de-pegging: USDT → $0.95
    - Correlation breakdown: stocks + bonds drop simultaneously
    - Liquidity drought: spread widens 10×
    - Exchange outage: primary exchange unreachable for 6 hours
* [+] **Stress test cadence:**
    - run on every new strategy before promotion
    - run quarterly on all live strategies
    - run on demand after market events
* [+] **Stress test reporting:**
    - max loss per scenario
    - time-to-recover
    - position liquidation feasibility
    - margin call probability
* [+] **Scenario library as code:**
    - YAML-defined scenarios
    - replay engine integration
    - parameterized scenarios (intensity, duration, asset scope)

Must explain:

* [+] რატომ historical replay > Monte Carlo for tail risk
* [+] რატომ stress test ქცევა > backtest performance
* [+] რატომ scenario library უნდა იზრდებოდეს ყოველ market event-თან

──────────────────────────────
[+] COUNTERPARTY & CUSTODY RISK (NEW SECTION — v5)
──────────────────────────────

Implement:

* [+] **Exchange counterparty risk monitoring:**
    - exchange health scorecard (volume, withdrawals, social signals)
    - exchange concentration limits (max % of capital per exchange)
    - early warning indicators (unusual withdrawal delays, social sentiment)
    - automated migration plan if exchange health degrades
* [+] **Stablecoin de-pegging risk:**
    - real-time USDT/USDC peg monitoring
    - automatic migration USDT → USDC if peg breaks > 1%
    - hold limits per stablecoin
    - cross-stablecoin arbitrage detection (signal of de-pegging)
* [+] **Custody options (crypto):**
    - exchange custody (default Stage 1-7) — fastest, highest counterparty risk
    - self-custody (hardware wallet) — slowest, lowest counterparty risk
    - qualified custodian (Coinbase Custody, BitGo) — middle ground
* [+] **Withdrawal latency monitoring:**
    - track withdrawal completion times
    - alert on degradation (> 2× historical average)
    - early FTX-style red flag detection
* [+] **Periodic withdrawal tests:**
    - withdraw small amount monthly to verify exchange solvency
    - document procedure
* [+] **Multi-exchange capital allocation:**
    - default no more than 50% per single exchange
    - automatic rebalancing on health degradation
* [+] **Hot/cold wallet separation:**
    - hot wallet: trading capital only (5-20% of total)
    - cold wallet: long-term holdings (80-95% of total)
    - automatic top-up rules

Must explain:

* [+] რატომ "not your keys, not your coins" applies to trading capital
* [+] რატომ FTX taught us "withdrawal latency = solvency signal"
* [+] რატომ exchange concentration > strategy concentration

──────────────────────────────
[+] RISK DECOMPOSITION & FACTOR ATTRIBUTION (NEW SECTION — v5)
──────────────────────────────

Implement:

* [+] **Factor risk attribution (Fama-French style):**
    - market beta exposure
    - size factor exposure
    - value factor exposure
    - momentum factor exposure
    - quality factor exposure
    - volatility factor exposure
* [+] **Systematic vs idiosyncratic decomposition:**
    - what % of P&L is from market moves?
    - what % is from strategy edge?
    - rolling decomposition (last 30/90/180 days)
* [+] **Sector exposure tracking (equities):**
    - tech / healthcare / financials / energy / etc.
    - sector concentration alerts
    - sector rotation tracking
* [+] **Crypto factor decomposition:**
    - BTC dominance correlation
    - ETH ratio correlation
    - market cap tier (large / mid / small)
* [+] **Currency exposure decomposition:**
    - USD-denominated P&L
    - USDT P&L
    - USDC P&L
    - cross-currency basis risk
* [+] **Risk attribution reporting:**
    - daily attribution report per strategy
    - weekly portfolio-level attribution
    - drift detection (factor exposures changing over time)

Must explain:

* [+] რატომ "your strategy's edge" might be hidden market beta
* [+] რატომ factor attribution prevents fooling yourself
* [+] რატომ sector rotation tracking matters for ETF strategies

──────────────────────────────
[+] LIQUIDITY RISK MANAGEMENT (NEW SECTION — v5)
──────────────────────────────

Implement:

* [+] **Liquidity scoring per asset:**
    - average daily volume (ADV)
    - bid-ask spread (bps)
    - market depth at multiple price levels
    - order book resilience (refill speed)
* [+] **Liquidity-adjusted position sizing:**
    - max position size = min(strategy_size, liquidity_score × ADV × allowed_pct)
    - default cap: 1% of ADV per asset
* [+] **Slippage prediction model:**
    - empirical slippage from historical fills
    - size-adjusted slippage curve
    - integrated into pre-trade risk check
* [+] **Time-to-liquidate estimate:**
    - given current position, how many days to fully exit at 1% ADV?
    - alert if > 5 days for any position
* [+] **Liquidity drought detection:**
    - spread widens > 2× normal → reduce position sizes
    - depth thins > 50% normal → reduce trading
    - VIX spike > 30 → equity liquidity reduced expected
* [+] **Crypto-specific liquidity:**
    - exchange-specific liquidity (BTC liquid on Binance, less so on Bittrex)
    - cross-exchange arbitrage liquidity
    - on-chain vs exchange liquidity (DeFi future)
* [+] **Stop-loss liquidity awareness:**
    - in low-liquidity windows, stops may slip badly
    - adaptive stop placement (wider in thin markets)

Must explain:

* [+] რატომ liquidity > volatility for position sizing
* [+] რატომ "liquid in normal markets" ≠ "liquid in stressed markets"
* [+] რატომ stop-losses can fail in low-liquidity windows

──────────────────────────────
[+] ORDER BOOK MICROSTRUCTURE (NEW SECTION — v5)
──────────────────────────────

(Relevant from Stage 2+ when websocket order book streams are integrated)

Implement:

* [+] **Order book imbalance signals:**
    - bid_size / (bid_size + ask_size) at top N levels
    - imbalance shift detection
    - imbalance as feature for strategies (Stage 8 ML)
* [+] **Bid-ask spread modeling:**
    - rolling spread statistics
    - spread regime detection (tight / normal / wide)
    - spread cost in execution
* [+] **Order flow imbalance:**
    - buy volume vs sell volume per minute
    - aggressor side classification
* [+] **Trade signing (Lee-Ready algorithm):**
    - classify each trade as buyer-initiated or seller-initiated
    - cumulative trade imbalance
* [+] **VPIN (Volume-Synchronized Probability of Informed Trading):**
    - flash crash early warning indicator
    - threshold-based alerts
* [+] **Top-of-book changes per second:**
    - high frequency = active market
    - low frequency = stale book risk
* [+] **Hidden order detection:**
    - iceberg detection via order book replay
    - known indicator of institutional activity

Must explain:

* [+] რატომ order book is informationally richer than OHLCV
* [+] რატომ VPIN warned of 2010 Flash Crash
* [+] რატომ trade signing ≠ trade direction (buyer-initiated does not mean prices go up)

──────────────────────────────
[+] INTERNAL CONTROLS & SEPARATION OF DUTIES (NEW SECTION — v5)
──────────────────────────────

Implement:

* [+] **Four-eyes principle for critical operations:**
    - production deployment requires PR + reviewer
    - manual position adjustment requires dual approval
    - secret rotation requires two operators
    - kill switch deactivation requires two confirmations
* [+] **Separation of duties:**
    - trader role vs operator role vs developer role (RBAC)
    - production access ≠ development access
    - audit log access ≠ writeable access
* [+] **Trade reversal procedures:**
    - documented procedure for incorrect trades
    - reverse trade flagging in audit log
    - financial impact accounting
* [+] **Position adjustment procedures:**
    - documented procedure for manual adjustments
    - reason required (free-text + category)
    - secondary approval if > $X impact
* [+] **Privileged action audit trail:**
    - every privileged action logged with operator ID
    - immutable log
    - daily review of privileged actions
* [+] **Privileged access reviews:**
    - quarterly review of who has what access
    - revoke unused access
    - access expiration policy

Must explain:

* [+] რატომ four-eyes prevents single-point-of-failure (human errors)
* [+] რატომ separation of duties = baseline financial controls
* [+] რატომ unused access = security risk

──────────────────────────────
[+] DATABASE ENGINEERING SPECIFICS (NEW SECTION — v5)
──────────────────────────────

Implement:

* [+] **TimescaleDB extension for time-series:**
    - hypertables for OHLCV, ticks, events
    - automatic partitioning by time
    - continuous aggregates for downsampling
    - retention policies (raw ticks → minutes → hours → daily)
* [+] **Partitioning strategy for large tables:**
    - audit_log partitioned monthly
    - ohlcv partitioned by year + symbol
    - automatic old partition archival to S3 (Stage 7)
* [+] **Index design for trading queries:**
    - composite indexes on (symbol, timestamp)
    - covering indexes for hot queries
    - BRIN indexes for large append-only tables
* [+] **Vacuum strategy for high-write tables:**
    - autovacuum tuning for hot tables
    - scheduled VACUUM ANALYZE
    - bloat monitoring
* [+] **Connection pooling:**
    - PgBouncer in front of Postgres (transaction mode)
    - asyncpg native pooling for hot connections
    - max_connections sized appropriately
* [+] **Read replicas (Stage 7+):**
    - analytics queries on replica
    - reporting queries on replica
    - main DB only for hot writes
* [+] **Backup strategy:**
    - continuous WAL archiving
    - daily full backup
    - weekly verification (restore to test env)
* [+] **Migration strategy:**
    - alembic for schema changes
    - never destructive in single migration (drop column = 2 migrations)
    - online migration for hot tables (concurrent index, etc.)
* [+] **DuckDB for analytics:**
    - in-process analytics on Parquet files
    - no separate server needed
    - integrates with pandas

Must explain:

* [+] რატომ TimescaleDB უმჯობესია vanilla Postgres-ზე time-series-ისთვის
* [+] რატომ partitioning > monolithic tables at scale
* [+] რატომ verified backup > untested backup

──────────────────────────────
[+] MULTI-TIER CACHING STRATEGY (NEW SECTION — v5)
──────────────────────────────

Implement:

* [+] **L1 cache (in-process, fastest):**
    - functools.lru_cache for pure functions
    - in-memory dict for hot lookups
    - TTL-based expiration
* [+] **L2 cache (Redis, shared across processes):**
    - Stage 7+ when Redis introduced
    - cross-process consistency
    - longer TTLs
* [+] **Cache invalidation strategies:**
    - TTL-based (default, simple)
    - event-based (on data update)
    - explicit (manual invalidation)
* [+] **Cache warming on startup:**
    - critical caches pre-loaded
    - avoid cold-start latency spikes
* [+] **Cache hit ratio monitoring:**
    - per-cache hit ratio in Prometheus
    - alert if hit ratio drops > 10% from baseline
* [+] **Cache size limits:**
    - bounded sizes (LRU eviction)
    - memory budget per cache
* [+] **Cache stampede prevention:**
    - request coalescing on cache miss
    - "stale-while-revalidate" pattern

Must explain:

* [+] რატომ multi-tier > single tier (different access patterns)
* [+] რატომ cache invalidation is hard (one of the 2 hard problems)
* [+] რატომ cache stampede can kill your DB

──────────────────────────────
[+] PLUGIN / EXTENSION ARCHITECTURE (NEW SECTION — v5)
──────────────────────────────

Implement:

* [+] **Plugin interface for new strategies:**
    - StrategyPlugin abstract base class
    - registration via entry points (setuptools)
    - hot-loading in dev (cold-load in prod)
* [+] **Plugin interface for new exchanges:**
    - ExchangePlugin abstract base class (extends ExchangeInterface)
    - feature flag per exchange
* [+] **Plugin interface for new data sources:**
    - DataProviderPlugin abstract base class
    - automatic registration on import
* [+] **Plugin interface for new alerting channels:**
    - AlertChannelPlugin abstract base class
    - Telegram, Discord, Slack, PagerDuty, custom webhook
* [+] **Versioned plugin contracts:**
    - semver per plugin interface
    - deprecation warnings
    - migration guides between major versions
* [+] **Plugin sandbox:**
    - resource limits per plugin
    - timeout enforcement
    - exception isolation (plugin crash != system crash)
* [+] **Plugin discovery:**
    - automatic discovery via entry points
    - explicit registration via config
    - audit log on plugin load

Must explain:

* [+] რატომ plugin architecture enables third-party extensions safely
* [+] რატომ versioned contracts prevent breaking changes
* [+] რატომ plugin sandbox prevents one bad plugin from killing system

──────────────────────────────
[+] SETTLEMENT, CUSTODY & WALLET MANAGEMENT (NEW SECTION — v5)
──────────────────────────────

Implement:

* [+] **Settlement tracking:**
    - T+1 for stocks (US, post-2024)
    - T+0 / instant for crypto
    - settlement-aware available cash calculation
    - settlement risk during multi-day positions
* [+] **Cash management:**
    - settled cash vs unsettled cash distinction
    - free vs withheld for orders
    - margin available calculation
* [+] **Cold wallet management (crypto):**
    - hardware wallet integration (Ledger, Trezor)
    - cold wallet address generation procedure
    - withdrawal whitelist for cold wallets only
    - periodic transfer to cold storage (configurable threshold)
* [+] **Hot wallet management:**
    - exchange wallet
    - max balance limit
    - automatic transfer to cold above threshold
* [+] **Withdrawal procedures:**
    - documented procedure
    - confirmation requirements (2FA + email)
    - audit log
    - delay/cooling-off period for first-time addresses
* [+] **Multi-sig for high-value operations (future):**
    - 2-of-3 multisig for cold wallet access
    - threshold signatures (Stage 8+)

Must explain:

* [+] რატომ T+1 settlement matters for capital efficiency
* [+] რატომ hot wallet should be < 10% of total
* [+] რატომ withdrawal whitelist > confirmation procedures

──────────────────────────────
[+] INTERNATIONALIZATION & OPERATOR UI LANGUAGES (NEW SECTION — v5)
──────────────────────────────

Implement:

* [+] **Operator UI bilingual support (Georgian + English):**
    - Stage 7 operator console: i18n via gettext or similar
    - all UI strings extracted to .po files
    - language toggle in UI
* [+] **Locale-aware formatting:**
    - currency display per locale (₾, $, €)
    - number formatting (1,000.00 vs 1.000,00)
    - date/time formatting (YYYY-MM-DD vs DD.MM.YYYY)
* [+] **Telegram bot bilingual responses:**
    - operator can choose language
    - critical alerts translated to both languages
* [+] **Documentation language separation:**
    - English: ADRs, technical docs, code comments
    - Georgian: user-facing UI, runbooks (operator-facing)
    - Bilingual: README.md, CLAUDE.md
* [+] **Tax report generation in Georgian:**
    - საქართველოს tax authority format
    - GEL-denominated columns
    - Georgian column headers

Must explain:

* [+] რატომ bilingual operator UI = better operational outcomes
* [+] რატომ tax reports must be in local language
* [+] რატომ technical docs stay English (searchability)

──────────────────────────────
END OF AUGMENTED SPECIFICATION (v5)
──────────────────────────────

──────────────────────────────
[+] HOW TO CONNECT TO THE TRADING-BOT REPO (v4 NOTE)
──────────────────────────────

GitHub repo: https://github.com/Gkamashidze/trading-bot

⚠️ Constraint: ამ Claude Code session-ის GitHub MCP tools restricted-ია `gkamashidze/wishmotors-tg-analyzer`-ზე. ამიტომ:

* GitHub MCP tools (PR creation, issue read, etc.) ვერ გამოვიყენებ ახალი repo-ს მიმართ
* მაგრამ ლოკალური bash + git tools არ არის შეზღუდული — შემიძლია clone, edit, commit, push

რეკომენდირებული workflow:

1. ახალი terminal session-ი:
   ```bash
   cd ~  # ან სასურველი parent dir
   git clone https://github.com/Gkamashidze/trading-bot.git
   cd trading-bot/
   claude  # ახალი Claude Code session ამ working dir-ში
   ```

2. ახალ session-ში გადავცემ ამ plan ფაილს, შემდეგ ვიწყებთ Stage 0 implementation-ს.

3. ALTERNATIVE: ამ session-ში ლოკალურად ვიქმნი (`/home/user/trading-bot/`), მე ვწერ ფაილებს, თქვენ git push-ი ხელით (ან ვცდილობ git push თქვენი authenticated session-ით).

──────────────────────────────
