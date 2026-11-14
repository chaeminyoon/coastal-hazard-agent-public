# Features and boundaries

This document describes the sanitized web/API source extract, not a production service or a complete bundled analysis engine.

## Query and spatial interaction

The interface supports region selection, map-based selection and review of analysis results. The backend provides a selection-scoped engine wrapper intended to apply the selected-grid scope when executing queries. Review the implementation and tests for its exact boundaries; this is not a general SQL-security proof.

## Report integration

Report jobs are managed asynchronously, with integration points for analysis, charts, narration, verification, assembly and conversion. A compatible external engine is required. The source extract alone does not reproduce the original assessment data or reporting pipeline.

Where available, results retain SQL, table data and report-evidence links. Numerical verification rules do not establish universal answer correctness, a measured false-positive rate or guaranteed fallback success.

## State and operations

The code includes authentication, user/session persistence, history, administrator operations, report-job handling and deployment examples. Example replica counts or local service addresses describe configuration, not independently verified running infrastructure, concurrency capacity or an SLA.

## Original portfolio materials and illustrations

[English-annotated original captures](assets/portfolio/README.md) show the workspace, executed SQL, selected-area analysis, report-evidence links and the reporting sequence: four screenshots and a three-frame GIF, alongside two original GeoSR logos for historical project context. Major UI labels and explanations are translated for portfolio readability while retaining the original layout, branding and workflow. The application interface and source remain Korean; these are not native-English runtime screenshots or an English-localized product. English SQL field labels and readable excerpts are reading annotations, not newly executed queries or a migrated schema. Opaque masks cover assessment figures, record rows/identifiers, detailed maps, selected scope literals and account information; no synthetic assessment values or replacement numerical results are supplied. All three GIF frames are English-annotated and data-protected, and playback speed is not execution latency. Full report PDFs and raw assessment files are not distributed.

The [edited internal engineering review](ENGINEERING_REVIEW.md) preserves important design decisions and dated findings while removing environment and data-specific details. It is not a current production vulnerability assessment.

The application user guide still uses separately labelled illustrative workflow schematics with no production data. These diagrams must not be confused with the original captures in the portfolio gallery.

## Not claimed

No hosted demo, bundled customer dataset, standalone full-service reproducibility, blanket factual accuracy, financial ROI, adoption rate, production availability or average performance is claimed. Current checks are recorded separately in VALIDATION.md.
