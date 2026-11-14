# Engineering Review: Coastal Hazard Analysis Agent

**Original review date: 2026-07-31.** This is an **edited portfolio excerpt, environment and data-specific details removed**, adapted from the internal service review and feature documentation.

The original review combined API exercises, inspection of generated artifacts, deployed-bundle inspection and source analysis. Browser inspection was limited after the connection was interrupted; backend tests were not run in the reviewed deployment because development dependencies were unavailable. Historical observations below describe that review, not the present service. No new runtime verification is claimed here.

## Architecture worth preserving

- **Evidence-linked analysis:** natural-language requests feed a DuckDB analysis engine; responses retain SQL, result tables and numerical-check metadata. Reports connect sentences to statistical evidence and map context. These mechanisms support inspection, not a blanket guarantee of correctness.
- **Server-controlled spatial scope:** the reviewed design recalculated intersecting grid identifiers from geometry instead of trusting client-provided identifiers. A temporary `selected_grid` relation represented the selection; regional baselines remained separate. The review specifically recommended correcting documentation that still described obsolete SQL rewriting.
- **Separated report execution:** generation used a Redis/RQ worker and a staged pipeline: ingest, analyze, visualize, narrate, verify, compose and convert. SSE exposed job progress. Markdown and HWPX were output formats, while edits were intended to preserve prior versions and validate changed content against available evidence.
- **User-scoped persistence:** conversations, scenarios, report artifacts and audit operations were designed around authenticated ownership. The review treated server-side ownership checks and upload/coordinate-system validation as engineering requirements, not merely UI controls.

## Historical findings and recommended decisions

These were findings or proposals on **2026-07-31**, not a current defect list.

1. **Make cancellation a durable state transition.** A live exercise observed a running report move from cancelled to completed. The review traced this to premature cancellation finalization and a worker that recognized only the pending-cancellation state. It recommended distinguishing queued from running work, recognizing both cancellation states, guarding persistence against overwriting cancellation, and adding race-condition regression tests.
2. **Preserve workflow continuity.** Source inspection identified missing SSE failure recovery, loss of in-memory work after reauthentication, and incomplete restoration of active report cards. Recommendations included reconnect/polling fallback, reauthentication without destroying the workspace, and saved-conversation restoration with job-state synchronization.
3. **Keep expensive work off request paths.** Report revisions and content conversion were recommended for the job queue. Other recommendations addressed synchronous database work in asynchronous paths, repeated per-connection polling, explicit DuckDB connection cleanup and retryable dependency-readiness checks.
4. **Treat grounded charts as a separate semantic-quality problem.** The review observed unsuitable aggregation of unit-bearing quantities and inconsistent grade colors. It proposed question-relevant column selection, unit-aware aggregation and a shared risk-grade palette. Evidence provenance alone did not establish that a chart was meaningful.
5. **Make interface failures visible.** The review recommended replacing accumulated global CSS overrides with component-level rules, exposing autosave/network errors, improving keyboard accessibility and avoiding unsupported mobile expectations. Report materials, generation settings, selection A/B comparison and account/session controls were proposed workflow improvements, not established by the review itself.

The proposed order was cancellation and continuity first, then UI/state cleanup, analytical workflow improvements, and operational/documentation maintenance.

## What the current public source supports

A targeted source check, separate from the historical review, found:

- `backend/coastal_web/report_queue.py` recognizes pending and final cancellation states and requests cancellation-preserving updates; `repositories.py` supplies the guarded update. These are implementation mechanisms, not proof of end-to-end race freedom.
- `api.py` routes report revisions through `submit_edit` when a report dispatcher is configured; a synchronous fallback also exists. Queue support must not be described as unconditional.
- `services.py` contains the selection-scoped wrapper, rejection of obsolete selection-table references, and checks for selection/baseline relation usage before marking an answer grounded. These checks are not a general SQL-security proof.

The current public `docs/FEATURES.md` describes a sanitized integration extract requiring a compatible external engine, not a standalone reproduction of the original service. No claim is made that other historical findings remain open or have been resolved, or that the source establishes accuracy, performance or production availability.

## Editorial and privacy boundary

Removed: raw/customer records and result values, detailed geospatial examples, deployment addresses, account identifiers, job identifiers, credentials, environment-specific operational details and artifact-location traces. Original feature descriptions informed the workflow summary; they were not treated as independent proof of present implementation. Media approval does not imply permission to expose data embedded in media.
