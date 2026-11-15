# README excerpts: provenance and scope

These images supplement the historical, English-annotated application captures in this folder. They are not all the same kind of evidence.

## Actual English React UI

- **english-ui-excerpt.png:** a crop of the actual English frontend rendered in a local, read-only archive review. English text is produced by React/TypeScript localization, not painted over a Korean screenshot. The private wrapper and unused bottom margin are cropped out; the application's read-only and unavailable-data notices remain visible. No analysis was submitted.
- **english-guide-excerpt.png:** a crop of the actual English guide dialog from the same local worktree. Its visible workflow schematics are explicitly illustrative, not captured production results.
- These captures do not demonstrate a live dataset-backed service, live map data or new report generation. They contain no loaded assessment records.

### Review source, not a silent main-branch replacement

[english-ui-localization.patch](english-ui-localization.patch) contains the actual frontend changes used for the English preview. It is supplied as an **unapplied review patch** against the existing public frontend snapshot; the main-branch frontend files have not been replaced. From the repository root, a reviewer can inspect the patch or apply it with `patch -p1 < docs/assets/portfolio/english-ui-localization.patch`. It does not include the private PDF, private archive-preview server, external engine or dataset.

The separate local review worktree passed **124 frontend tests in 12 files**, TypeScript checking and a Vite production build, retaining the original 108 tests and adding 16. Local validation used Node 26.5.0 with `--no-webstorage` and same-version Rollup/esbuild WASM tooling overlays; dependency manifests were unchanged. These are local review results, not a claim that the main branch's CI or backend passed 124 tests. The loopback-only private preview separately passed 34 safety checks; that adapter is not distributed.

UI text and Canadian-English formatting were localized. API/protocol identifiers, raw SQL, database/schema names, stored/user content and the Korean report-writing command were not translated into new machine values.

## Original generated report excerpts

- **report-cover-excerpt.png:** the heading of the original Korean report for Busan Metropolitan City, Suyeong-gu, dated **14 July 2026**. This is a cover excerpt, not a newly generated English report.
- **report-regional-chart-excerpt.png:** the original regional aggregate chart comparing the share of grade-4/5 high-risk grid cells by neighbourhood. Korean labels, numerical annotations, bar geometry and colours are retained. This is a selected aggregate visualization, not a release of grid-level records.
- Both are pixel crops of the existing `docs/assets/report-sample/report-cover.png` and `report-region-analysis.png` project assets from source snapshot `5f8d408e612191ee617efebd587b8eb65c37f277`. The corresponding private 24-page PDF has SHA-256 `4802c429b9fff31817e1892146475205edd728016a398555653d2813be9116c3`.
- The full PDF, detailed risk-map figure, raw-data tables, grid identifiers, coordinates and underlying GeoPackage/CSV data are **not uploaded**. Crops remove the rest of each source image; no hidden pixel layer or source-document attachment is embedded in these flattened PNGs.
- The original chart's displayed values describe that archived report only. They are not new model-performance measurements, a correctness guarantee, a current hazard advisory or evidence that the missing external engine ran in this public extract.

## Attribution and permissions

Selected project/report figures are shared for portfolio review with publication permission. The separately prepared assessment dataset is not claimed as the author's work or redistributed as a dataset. Original GeoSR branding identifies the historical project context, not a new endorsement. Public visibility is not a general open-source, dataset or trademark licence grant.
