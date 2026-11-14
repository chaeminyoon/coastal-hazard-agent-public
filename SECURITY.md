# Security and data handling

This repository is a sanitized portfolio source extract, not a production deployment or security certification.

- Keep real credentials, API keys, tokens, datasets, customer documents, session exports and generated reports outside Git.
- Copy example configuration locally and replace every placeholder before any deployment. Keep local .env files ignored.
- Configure TLS, origin allowlists, trusted proxy behavior and access controls for your environment. Example local bindings and Compose services are not a public-service recommendation.
- Supply only data and external engines you have permission to use. Review map-provider terms before enabling map layers.
- Review backup/restore and administrator commands before use; restoration can overwrite data.

Do not put credentials or customer information in public issues. Agree a private reporting channel with the maintainer for sensitive security findings. This repository contains no historical internal vulnerability-review report.
