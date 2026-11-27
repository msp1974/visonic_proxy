# Changelog

All notable changes to this fork of `visonic_proxy` are documented in this file.

## [Unreleased]

## [1.3.2] - 2026-11-27

### Fixed
- Forward initial Alarm frames (such as `HELLO` `0d 06 f9 0a`) to `VISONIC` even while the Visonic client is still in `CONNECTING` state so `FlowManager` holds and delivers them once the TCP handshake completes, preventing 60 s PowerManage disconnect loops on restart.
- Set `account_id="0"` on `NonPowerLink31Message` frames sent to `Alarm` (`CM`/`HASS` → `Alarm`) to match the PowerLink 3.1 protocol.

## [1.3.1] - 2026-11-27

### Fixed
- Send graceful PowerLink 3.1 `DISCONNECT_MESSAGE` to connected alarm panels on `ConnectionManager.stop()` so the panel resumes HTTPS polling and reconnects automatically after an add-on restart.
- Cap upstream PowerManage `ka_time` to `10` s in `/scripts/update.php` responses and strip mismatched `Content-Encoding` / `Transfer-Encoding` / `Connection` headers when forwarding or rewriting HTTPS responses.
- Emit uppercase hexadecimal `length` in `MessageBuilder.build_powerlink31_message` to match native PowerLink 3.1 wire frames.

## [1.3.0] - 2026-11-27

### Added
- Native Home Assistant add-on translations (`translations/es.yaml`, `translations/en.yaml`) and in-UI documentation (`DOCS.md`) clarifying each port and integration mode.

### Changed
- Grouped WebSocket add-on options under nested `websocket: {enabled, ssl, auth_key}` in `config.yaml` and `run.sh` (with backwards-compatible parsing in `helpers/env.py` for flat options/env vars) and clarified `ports_description`.

## [1.2.0] - 2026-11-27

### Added
- Automated CI workflow (`.github/workflows/ci.yml`) running `unittest`, `ruff`, and `mypy` on Python 3.12 and 3.13.
- Comprehensive regression test suites covering concurrency, P0 security/stability fixes, and P1 reliability/add-on lifecycle (`tests/test_p0_security_and_stability.py`, `tests/test_p1_reliability_and_addon.py`).
- Persistent TLS certificate path resolution (`get_ssl_certs_path`) storing add-on certificates under `/data/certs` with `0o600` private key permissions and cryptographic serial numbers.
- Graceful `SIGINT`/`SIGTERM` shutdown handling in `visonic_proxy/run.py`.
- Dedicated `visonic_proxy/connections/visonic_client.py` module extracted from `websocket.py` (with backwards-compatible re-exports).

### Changed
- Replaced `asyncio.sleep` polling loops in `VisonicClient.wait_for_responses` and `wait_for_empty_queue` with `asyncio.Event` + `asyncio.wait_for` and `asyncio.Queue.join()`.
- Deduplicated checksum calculation in `MessageBuilder`, reused a single `B0Formatters` instance in `B0Decoder`, and removed unused `visonic_proxy/connections/httpserver/make_certs.py`.
- Synchronized `setup.py` dependencies/URL with `requirements.txt` and updated `websocket_commands.md` with valid JSON, `siren`/`use_42` documentation, and authentication notes.
- `run.sh` now exports all `config.yaml` options and launches Python via `exec`.
- `config.yaml` uses `password?` for `websocket_auth_key`, removes deprecated `legacy: true`, and targets 64-bit architectures `aarch64` and `amd64` (aligned with `build.yaml` and `Dockerfile`).
- `Dockerfile` label `io.hass.version` aligned to `1.1.2`.
- `helpers/env.py` loads `/data/options.json` with typed coercion (`bool`, `int`, `float`, `LOG_LEVEL`) without mutating `Config` class attributes, and redacts sensitive keys in logs.
- `Watchdog` and `ServerConnection` keepalive timers migrated to `time.monotonic()`.
- Updated Ruff configuration in `pyproject.toml` to remove obsolete rules (`S320`, `PT004`, `UP038`), resolved all Ruff findings across `visonic_proxy/`, and expanded CI to run global `ruff check visonic_proxy` plus `mypy` across 15 typed core modules.

### Fixed
- **Security:** prevented path traversal and JPEG `\r\n` truncation in `Webserver.decode_image` (with non-blocking `asyncio.to_thread` saving), added a 5 MiB `Content-Length` limit (`413`) and malformed-request validation (`400`) in `httpserver`, switched WebSocket Bearer auth to `hmac.compare_digest`, and redacted sensitive settings/keys from logs.
- **Protocol & WebSocket:** fixed `await` precedence bug in `VisonicClient.set_pgm` with duration, fixed `SENSOR_TYPES` indentation in `get_device_info`, fixed hex length formatting in `MessageBuilder._build_b0_generic_request`, fixed invalid `field(default_factory={})` in `B0Message`/`STDMessage`, propagated `InvalidMessageException` cleanly from `B0Decoder.decode`, hardened `websocket_receive_message` input validation, safe `broadcast` iteration, and `subscribed_messages` cleanup on disconnect.
- **Asyncio & Reliability:** added per-connection PowerLink 3.1 TCP frame reassembly and exception isolation in `FlowManager`, prevented `pending_has_connected` deadlocks on failed connections, added 10 s connect timeout and `Watchdog`/listener cleanup in `ClientConnection`, isolated listener failures in `Events`, hardened `DataStore` paged-response merging and EPROM bounds, and matched clients by `(ip, port)` in `ServerConnection`.

## [1.1.2] - Fork baseline
- Improved concurrency when the Visonic mobile app (PowerManage) and Home Assistant access the alarm simultaneously (channel transaction arbitration, response isolation, independent `msg_id` sequence translation with CRC16 recalculation).
- Non-blocking HTTPS `/scripts/update.php` forwarding and filtering of duplicate `connect` commands when the panel is already connected.
- Initial `unittest` suite (`python -m unittest discover -s tests -v`).
