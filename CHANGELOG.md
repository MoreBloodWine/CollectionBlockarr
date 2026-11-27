# Changelog

## v1.0.1 (2026-11-27)
- Added background sweep thread (every 60s) with thread-safe sweep lock so scheduled Jellyfin scans never leave blocked collections behind.
- Fixed missing `threading` / `_retry_timer` crash in 5-minute health retest.
- Added in-app Changelog modal and direct GitHub link in top bar.

## v1.0.0 (2026-11-26)
- Initial release: Jellyfin BoxSet blocking, `TmdbCollection` stripping, instant JSON restore snapshots, real-time webhook interception, health checks, and full-state export/import.
