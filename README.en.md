# gis-agent-bridges

中文版：[`README.md`](README.md)

A family of small, safety-gated bridges that let AI agents operate
mainstream GIS software — headless inventory/backup plus, where the
vendor API allows, a live in-app MCP bridge — all in one repo for easy
reuse. The collection now has **16 packages and 127 MCP tools**: nine
desktop GIS bridges, five consumer-side read-only bridges (pgRouting,
istSOS / OGC SensorThings API, PostGIS, GeoServer and STAC API), and
two headless tool bridges (GRASS GIS and GDAL/OGR).

Every bridge follows the same rules: localhost-only listeners, a random
per-launch token, a `confirm=true` gate on content-level writes,
originals never modified (work happens on backup copies), no arbitrary
code execution tool, and honest per-mode calibration labels.

## Packages

| Software | Directory | Form | MCP tools | Status |
|---|---|---|---|---|
| SuperMap iDesktopX | `supermap/` | Live + headless | 13 | Package v0.4 (live server 0.3.0) · file-fallback mode calibrated on real iDesktop 10i (13/13); iDesktopX live mode unverified |
| ArcGIS Pro | `arcgis-pro/` | Live + headless | 13 | v0.2 · not real-machine calibrated |
| ArcMap (retired by Esri; personal use) | `arcmap/` | Live + headless | 10 + 6 headless actions | v0.3 · headless bridge calibrated on Desktop 10.8 / Python 2.7.16 (2026-10-25); live bridge uncalibrated |
| QGIS | `qgis/` | Live + headless | 12 | v0.2 · not real-machine calibrated |
| GeoScene Pro | `geoscene/` | Live + headless | 13 | v0.2 · compatibility unverified on real software |
| MapGIS | `mapgis/` | Probe + headless skeleton | 3 | Exploratory v0.2 · live interface unproven |
| ENVI | `envi/` | Headless only | 7 | v0.2 · idlpy path untested on real software |
| Global Mapper | `globalmapper/` | Headless + script semi-live | 7 | v0.2 · API signatures await probing |
| FME | `fme/` | Headless runner only | 6 | v0.2 · complements the official Flow MCP |
| pgRouting (OSGeo) | `pgrouting/` | Consumer read-only (stdio, no listener) | 5 | v0.1 · fixed parameterized templates for `pgr_dijkstra`, network summary and GeoJSON export; no arbitrary SQL; protocol selftest 12/12 with a fake psql shim; not real-machine calibrated; not an official pgRouting component |
| istSOS (OGC SensorThings API) | `istsos/` | Consumer read-only (stdio, no listener) | 6 | v0.1 · read-only STA tools with hard caps; protocol selftest 12/12 against a local fake STA server; istSOS4 itself untested; not an official istSOS component |
| PostGIS (PostgreSQL spatial extension) | `postgis/` | Consumer read-only (stdio, no listener) | 6 | v0.1 · fixed SQL templates via a psql subprocess (table list / columns / summary / GeoJSON export, allow-list plus export hard cap), no arbitrary SQL; protocol selftest 13/13 with a fake psql shim; not real-machine calibrated; not an official PostGIS component |
| GeoServer (OGC map server) | `geoserver/` | Consumer read-only (stdio, no listener) | 6 | v0.1 · read-only REST catalog tools (workspaces / layers / layer detail / WMS·WFS capabilities summary), GET-only, credentials via env only, same-origin link following; protocol selftest 12/12 against a local fake GeoServer; not real-machine calibrated; not an official GeoServer component |
| STAC API (spatiotemporal asset catalog) | `stac/` | Consumer read-only (stdio, no listener) | 6 | v0.1 · read-only STAC API search tools (collections / collection detail / item search / GeoJSON export, local bbox validation, hard caps, asset keys only — no downloads); protocol selftest 13/13 against a local fake STAC server; not real-machine calibrated; not an official component |
| GRASS GIS (OSGeo) | `grass-gis/` | Headless batch only (stdio, no listener) | 7 | v0.1 · fixed templates over `grass --exec` (map listing / raster info read-only; slope-aspect / hillshade / resample jobs and vector export behind the confirm gate, never `--overwrite`); protocol selftest 15/15 with a fake grass shim and a file-only location; not real-machine calibrated; not an official GRASS GIS component |
| GDAL/OGR (OSGeo) | `gdal/` | Headless tools only (stdio, no listener) | 7 | v0.1 · fixed templates over gdalinfo/ogrinfo reads and gdal_translate/ogr2ogr conversions (no raw option passthrough, subprocesses forced `GDAL_PAM_ENABLED=NO`, conversions behind the confirm gate and new files only); protocol selftest 15/15 with four fake-binary shims; not real-machine calibrated; not an official GDAL component |

## Quick start

```bash
git clone https://github.com/YUYU20061107/gis-agent-bridges.git
cd gis-agent-bridges
python scripts/quickstart.py --list
python scripts/quickstart.py --package qgis --selftest
python scripts/quickstart.py --sample-qgis
python scripts/quickstart.py --package qgis --print-config
```

Repository tooling is verified on Python 3.11+. Vendor runtimes differ
(SuperMap headless uses its bundled Python 3.5.4; ArcMap uses Python
2.7.16). A protocol selftest passing does **not** mean a package is
calibrated on real software — follow each package's
`docs/CALIBRATION.md` before production use.

Client configuration locations are in `docs/CLIENTS.md`; common
failures are in `docs/TROUBLESHOOTING.md`; the three-level version
scheme (repo Release / package version / MCP server version) is in
`docs/VERSIONING.md`.

## Design principles

- **Localhost only**: in-app bridges bind `127.0.0.1` with a random
  per-launch token. Desktop packages read the token file automatically;
  the two consumer bridges take the current `_token` as a tool argument.
- **Confirm gate**: content-level writes refuse to run without
  `confirm=true`, which only the user may authorize.
- **Originals read-only**: inventory and writes happen on timestamped
  backup copies, never on the original file.
- **No arbitrary execution**: no eval/exec, arbitrary script, arbitrary
  SQL or arbitrary URL tools — only enumerated, auditable tools.
- **Honest labels**: file-fallback is not live access; a passing
  selftest is not calibration; unverified interfaces return structured
  errors instead of pretending to work.

## Calibration evidence

Only two results are real-machine calibrated so far: SuperMap
file-fallback mode on iDesktop 10i (13/13 tools, 2026-10-24) and the
ArcMap headless bridge on Desktop 10.8 (georeferencing regression RMS
2.3884 m, 2026-10-25). Everything else is protocol-selftest level or
unverified, per package and per mode — see the Chinese README's
calibration section and each package's `docs/CALIBRATION.md` for the
full record. Never transfer one package's conclusion to another.

## Security

See [`SECURITY.en.md`](SECURITY.en.md) for the threat model, the
consumer-bridge database/network surfaces, and how to report a
vulnerability privately.

## License

MIT (see `LICENSE`; each package also carries a copy). This project is
not affiliated with SuperMap, Esri, NV5, Blue Marble Geographics,
Safe Software, OSGeo, pgRouting or istSOS; product names only identify
integration targets. You must supply your own licensed GIS software;
no vendor components are distributed.
