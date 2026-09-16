# ScarletX 0.4.6

ScarletX 0.4.6 packages the latest approved UI and deployment reliability changes into a stable release.

## UI

- Ships the approved compact desktop sidebar at 242px with 44px navigation rows, 15px labels, 19px icons, and tighter spacing.
- Preserves the existing 980px tablet rail and mobile layout.
- Preserves the approved wordmark, favicon, dashboard banner, and real application footer.

## Runtime and deployment

- Preserves the extracted shared frontend runtime (`runtime_core.js`) and its load order.
- Aligns standard Docker Compose backend health checks with the lightweight health contract used by TrueNAS.
- Keeps backend and web container versions synchronized at 0.4.6.

## TrueNAS

- Advances the TrueNAS application package to 1.0.12.
- Pins backend and web images to 0.4.6.
