# Validation record

This record concerns the sanitized public source, not the original operational deployment. No live customer dataset, provider API credential, production database or external reporting engine is used in these checks.

## Frontend

Node 24.14.0. Full Vitest suite: **108 passed across 8 files**, exit 0, with no unhandled errors. TypeScript and Vite build: passed, exit 0. Tests were also run with host TZ=America/Regina; UTC is set only inside test workers, while application display remains locale-aware.

This macOS environment rejected loading native Rollup under its runtime system policy. Validation used the official same-version Rollup/esbuild WASM implementations overlaid only in local node_modules. The committed package manifest and lockfile were not changed for this workaround. This is not a native-binary or Linux-container build validation.

## Backend

Python 3.13.12: dependency installation succeeded, but the local full-suite attempt stopped with 11 collection errors because macOS system policy rejected loading newly installed native SQLAlchemy, pydantic-core and NumPy extensions. This is not a passing backend test result; no system security settings were changed.

A manual Linux workflow (Python 3.12, normal GitHub-hosted Ubuntu runner) is included in .github/workflows/validate-public-source.yml. It is guarded to run only when this separate repository is public. Its backend and native frontend results must be checked independently; they are not implied by the local frontend result.

PostgreSQL integration requires COASTAL_TEST_DATABASE_URL. HWPX integration requires the separately provisioned coastal_agent module. A dependency-related skip is not evidence that the external integration passed.

## Limits

These checks do not measure response-time SLA, production concurrency, model quality, general factual accuracy, financial savings or operating adoption. Removed private operational captures are not used as evidence for this release.
