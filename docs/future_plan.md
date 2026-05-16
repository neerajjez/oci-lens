# OCI-Lens: Future Roadmap & Deep Planning

This document outlines the strategic evolution of `oci-lens` from a local CLI script into a battle-tested, production-ready observability platform. It details architectural decisions, feature evaluations, and a traceable implementation plan.

---

## 1. Storage Backend: Transitioning to a Database

Currently, `oci-lens` relies on raw JSON files. To support historical trends, a web GUI, and faster analytics, we need a persistent datastore.

### Evaluation: SQLite vs Time-Series Database (TSDB)
*   **TSDB (Prometheus/InfluxDB/TimescaleDB)**: Great for high-frequency (per-second) polling. However, it introduces significant infrastructure overhead and deployment complexity.
*   **SQLite**: Zero-configuration, serverless, and highly portable. 
*   **Decision**: **SQLite**. Since `oci-lens` collects data periodically (e.g., daily or weekly) rather than streaming live metrics, SQLite is the perfect fit. It easily handles millions of rows, integrates seamlessly with Python (`sqlite3` / `SQLAlchemy`), and keeps the tool portable.
*   **Architecture Impact**: Replace the `raw/*.json` saving mechanism with an `insert_to_db()` pipeline. 

---

## 2. Web GUI & Dashboard

Moving beyond static PDF reports to an interactive dashboard allows for dynamic filtering, drill-downs, and trend analysis.

### Evaluation: Streamlit
*   **Why Streamlit?** Since the backend is heavily Python and Pandas, Streamlit is the perfect bridge. It allows us to build a Grafana-like experience natively in Python without needing a separate React/Vue frontend.
*   **Features to build in GUI**:
    *   **Cost vs. Utilization Overlay**: Visualize if high spend correlates with high CPU/Memory usage.
    *   **Historical Trending**: Show cost drift over months (made possible by the new SQLite backend).
    *   **Filtering**: Slice by Tenancy, Compartment, Region, or Tag.

---

## 3. Real-Time Currency Conversion

OCI bills primarily in USD (or base local currency), but multi-national teams need localized reporting.

*   **Implementation Strategy**: 
    1.  Fetch the base cost from OCI (usually USD).
    2.  Integrate a free tier exchange rate API (e.g., *Frankfurter*, *ExchangeRate-API*, or *Open.er-api*).
    3.  Fetch rates for the top 15 global currencies daily and **cache them in SQLite** to respect API rate limits.
    4.  Allow the Streamlit GUI and CLI to switch display currencies dynamically using the cached rates.

---

## 4. Email Branding & Templating Engine

Organizations want reports that look internal and professional, rather than generic tool outputs.

*   **Implementation Strategy**:
    *   Keep it simple: Avoid complex, deep HTML editors.
    *   Introduce `Jinja2` for email generation.
    *   Add a `branding` block to `config.yaml`:
        ```yaml
        branding:
          primary_color: "#E63946"
          logo_url: "https://company.com/logo.png"
          company_name: "Acme Corp"
        ```
    *   Inject these variables into a sleek, pre-designed HTML template before dispatching the email.

---

## 5. Advanced Analytics Improvements

To make the tool highly valuable for production environments, the analytics engine needs to graduate from simple static thresholds.

*   **Predictive Exhaustion**: Calculate the rate of storage or compute growth and alert if a resource will hit 100% within 30 days.
*   **Reserved Instance (Capacity) Recommendations**: Analyze baseline steady usage and recommend converting on-demand instances to reserved capacities to save money.
*   **Zombie Resource Detection Deep-dive**: Identify detached block volumes, unattached IP addresses, and empty load balancers that incur costs.

---

## 6. Architectural Refactoring & CLI Expansion

Addressing current technical debt to prepare for enterprise scaling.

### Codebase Refactoring
1.  **Extract `main.py`**: Break the 1,500-line monolith into `cli.py`, `orchestrator.py`, and `presenter.py`.
2.  **Concurrent Fetching**: Implement `concurrent.futures.ThreadPoolExecutor` in `src/collector/compute.py` to fetch OCI metrics in parallel, dramatically reducing collection time for large fleets.

### CLI Expansion (New Flags)
Expanding the CLI to support the new database and reporting features.

| Flag | Purpose |
| :--- | :--- |
| `--concurrency N` | Set the number of parallel threads for OCI API calls (default: 10). |
| `--format [table\|json\|csv]` | Output format for terminal reports. |
| `--export-db path/to/export` | Dump the SQLite database to CSV/JSON for external BI tools. |
| `--currency EUR` | Force the CLI report to convert and display in a specific currency. |
| `--date-range [30d\|90d\|ytd]` | Quickly query specific historical windows from the database. |
| `--what-if thresholds.yaml` | Pass alternative thresholds to test savings without altering the main config. |
| `--gui` | Launch the local Streamlit dashboard server. |

---

## 7. Traceability Planning Matrix

A structured roadmap defining priority, effort, and architectural dependencies.

| Feature / Task | Priority | Effort | Prerequisites | Architectural Impact |
| :--- | :---: | :---: | :--- | :--- |
| **1. Refactor `main.py`** | **P0** (Critical) | Medium | None | Low risk, high reward. Must happen before adding new features. |
| **2. Concurrent API Fetching** | **P0** (Critical) | Medium | None | Changes `collector` logic. Drastically speeds up execution. |
| **3. SQLite Integration** | **P1** (High) | High | P0 Refactor | Replaces raw JSON. Requires building an ORM / schema layer. |
| **4. Advanced Analytics** | **P1** (High) | Medium | SQLite Integration | Enhances `engine.py`. Requires historical data from DB. |
| **5. Currency API Integration** | **P2** (Medium) | Low | SQLite Integration | Minor change. Requires a new collector script and DB table. |
| **6. Streamlit Web GUI** | **P2** (Medium) | High | SQLite Integration | New application layer. Sits on top of the SQLite DB. |
| **7. Email Branding via Jinja2** | **P3** (Low) | Low | None | Isolated change entirely within `src/notifier/`. |
| **8. Expanded CLI Flags** | **P3** (Low) | Low | Respective features | Tied to the completion of the features above. |

---

### Next Steps
The immediate focus should be **P0**: splitting `main.py` into manageable modules and implementing threaded API calls. Once the foundation is solid, **P1** (SQLite) will unlock the true potential of the Web GUI and historical analytics.
