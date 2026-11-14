# Validation record

This record concerns the sanitized public source, not the original operational deployment. No live customer dataset, provider API credential, production database or external reporting engine is used in these checks.

## Frontend

Node 24.14.0. Full Vitest suite: **108 passed across 8 files**, exit 0, with no unhandled errors. TypeScript and Vite build: passed, exit 0. Tests were also run with host TZ=America/Regina; UTC is set only inside test workers, while application display remains locale-aware.

This macOS environment rejected loading native Rollup under its runtime system policy. Validation used the official same-version Rollup/esbuild WASM implementations overlaid only in local node_modules. The committed package manifest and lockfile were not changed for this workaround. This is not a native-binary or Linux-container build validation.

### Independent Linux frontend check

[Linux run 43623727657](https://github.com/chaeminyoon/coastal-hazard-agent-public/actions/runs/43623727657) used Ubuntu 24.04, Node 24.14.0 and the committed dependency lockfile without the local WASM workaround. **108 tests passed across 8 files**, and TypeScript/Vite build passed. The [corrected follow-up run 43624718561](https://github.com/chaeminyoon/coastal-hazard-agent-public/actions/runs/43624718561) independently passed the same 108 frontend tests and TypeScript/Vite build.

## Backend

Python 3.13.12: dependency installation succeeded, but the local full-suite attempt stopped with 11 collection errors because macOS system policy rejected loading newly installed native SQLAlchemy, pydantic-core and NumPy extensions. This is not a passing backend test result; no system security settings were changed.

A manual Linux workflow (Python 3.12, normal GitHub-hosted Ubuntu runner) is included in .github/workflows/validate-public-source.yml. It is guarded to run only when this separate repository is public. Its backend and native frontend results must be checked independently; they are not implied by the local frontend result.

### First Linux full-suite result

[Run 43623727657](https://github.com/chaeminyoon/coastal-hazard-agent-public/actions/runs/43623727657), commit `dc1f095437c22920b1f0c94c0e2c7bdb94230810`, used Ubuntu 24.04 and Python 3.12.16. Actual pytest result: **177 passed, 6 failed, 2 skipped**, 180 warnings, 10.15 seconds. There were no collection errors.

- One API-root test failed because the backend job had not built `frontend/dist`.
- Four report-manager tests and one spatial-join test failed with missing `coastal_agent` imports. That separate engine package is not distributed in this repository.
- The initial workflow incorrectly reported a green backend job: `pytest | tee` ran under a shell without `pipefail`. That green status is **not a backend pass**. The workflow has been corrected to propagate test exit status and build frontend assets before API tests; tests and assertions have not been removed or weakened.

### Corrected Linux full-suite result

[Run 43624718561](https://github.com/chaeminyoon/coastal-hazard-agent-public/actions/runs/43624718561), commit `0c308091b4015c0ebc2508bd342fbdce2239492c`, used the corrected workflow. Actual pytest result: **178 passed, 5 failed, 2 skipped**, 180 warnings, 10.86 seconds. Pytest returned exit code 1 and the backend job correctly failed.

The API-root test passed after frontend assets were built. All five remaining failures are missing `coastal_agent` imports in report-verification and spatial-join tests. No tests or assertions were removed, weakened or newly skipped. The complete backend suite therefore remains **not passing** without the separate compatible engine package; no end-to-end engine success is claimed.

PostgreSQL integration requires COASTAL_TEST_DATABASE_URL. HWPX integration and the failing report-verification/spatial-join tests require the separately provisioned `coastal_agent` module. A dependency-related skip is not evidence that the external integration passed.

## Limits

These checks do not measure response-time SLA, production concurrency, model quality, general factual accuracy, financial savings or operating adoption. Removed private operational captures are not used as evidence for this release.
