# Features and boundaries

This document describes the sanitized web/API source extract, not a production service or a complete bundled analysis engine.

## Query and spatial interaction

The interface supports region selection, map-based selection and review of analysis results. The backend provides a selection-scoped engine wrapper intended to apply the selected-grid scope when executing queries. Review the implementation and tests for its exact boundaries; this is not a general SQL-security proof.

## Report integration

Report jobs are managed asynchronously, with integration points for analysis, charts, narration, verification, assembly and conversion. A compatible external engine is required. The source extract alone does not reproduce the original assessment data or reporting pipeline.

Where available, results retain SQL, table data and report-evidence links. Numerical verification rules do not establish universal answer correctness, a measured false-positive rate or guaranteed fallback success.

## State and operations

The code includes authentication, user/session persistence, history, administrator operations, report-job handling and deployment examples. Example replica counts or local service addresses describe configuration, not independently verified running infrastructure, concurrency capacity or an SLA.

## Illustrations

The user guide uses newly drawn workflow schematics. Every schematic is labelled illustrative and contains no production data. Original company logos, operating captures, GIFs, map screenshots and real report exports are excluded. The application interface itself remains Korean-language.

## Not claimed

No hosted demo, bundled customer dataset, standalone full-service reproducibility, blanket factual accuracy, financial ROI, adoption rate, production availability or average performance is claimed. Current checks are recorded separately in VALIDATION.md.
