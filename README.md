# Coastal Hazard Intelligence Agent

**Sanitized portfolio source for a geospatial analysis and evidence-linked reporting web application.**

I co-developed the system with an AI-team colleague, connecting map-based selection, scoped SQL, analysis, visualization, numerical checks and report preparation. The source assessment dataset was prepared separately; this work does not claim ownership of that dataset.

## Why this exists

GIS selection, analysis tables, charts and report writing often live in separate tools. This application connects them while keeping executed queries and supporting results available for review.

## Engineering decisions

- **Server-side selection scope:** selected grid IDs constrain subsequent queries rather than only changing the displayed map.
- **Evidence-linked results:** retain executed SQL, result tables and available report evidence so a reviewer can trace a figure back to its source.
- **Separate interactive and background work:** FastAPI handles requests while Redis/RQ coordinates report jobs. PostgreSQL persists users, sessions and history.
- **Explicit reporting stages:** integrate ingest, analysis, visualization, narration, verification, assembly and conversion through a separate reporting engine.
- **MCP integration:** pass scoped analysis results to data-analysis and charting tools.

These are implementation/design features, not guarantees of universal factual accuracy, zero hallucinations or production availability.

## What this public copy contains

- Python/FastAPI web and service-integration code
- React/TypeScript UI, including a Korean-language application interface
- Deployment examples, schema migrations and automated tests
- English workflow schematics labelled **Illustrative workflow, no production data**

It excludes original assessment files, customer documents, real report exports, production screenshots/GIFs, employer logos, internal service-review notes and the original private Git history. The schematics are not captures of a deployed system and are not benchmark evidence.

## Important dependency boundary

**This is a source extract, not a clone-and-run end-to-end demo.** The original workflow needs a separately provisioned compatible analysis/report engine, its coastal_agent Python package and compatible geospatial data. Those components and the underlying assessment dataset are not distributed here.

The checked-in configuration uses generic paths and placeholder values. Configure your own engine path and runtime secrets; never deploy with example credentials. The application does not provide a public hosted endpoint.

## Stack

Python, FastAPI, React, TypeScript, DuckDB, GeoPackage, PostgreSQL, Redis/RQ, Docker Compose and Nginx. The external reporting integration uses LangGraph, and visualization integrates [Data-Analyze-MCP](https://github.com/chaeminyoon/Data-Analyze-MCP).

## Development and validation

Use **Node 24.14 or later in the Node 24 line** for the frontend. The original container runtime targets Python 3.12; see the validation record for the Python version actually tested for this public copy.

### Frontend-only checks

~~~sh
cd frontend
npm ci
npm test
npm run build
~~~

A frontend build is not evidence that the dataset-backed service can run without its external dependencies.

### Backend checks

Install the declared requirements in an isolated Python environment, then run **python -m pytest -q tests** from the repository root. PostgreSQL integration tests require an explicitly supplied test database. The external-engine-specific HWPX test is skipped when its optional engine module is unavailable; this is not an end-to-end engine validation.

See [validation details](docs/VALIDATION.md), [feature boundaries](docs/FEATURES.md) and [security guidance](SECURITY.md). Historical operational timings and test counts from the private system are intentionally not reused as current results.

## Data, attribution and licensing

This source is shared for portfolio review with release permission. Public visibility is not a general open-source license grant. Third-party dependencies and map services retain their own licenses and terms; see [third-party notes](THIRD_PARTY_NOTICES.md). No original imagery or assessment data is redistributed.
