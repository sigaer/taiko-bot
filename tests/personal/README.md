# Personal display migration validation

`events.py` loads the installed wheel's actual NoneBot matchers and dispatches
OneBot and official QQ events. Its reference extracts the original functions from
Taiko d396bda / Sakura db0ac3e; only filesystem roots, synthetic binding SQL and
transport are replaced. Successful cases require an image and identical PNG
SHA256/dimensions, so two errors cannot pass image parity. QQ Markdown URLs are
resolved to fixture cache bytes; transient timestamp/UUID URL names are normalized.

Use separate center/client environments. Invoke with `--host`, `--baseline`,
`--work`, `--assets` (public assets only), and `--application` (this checkout).
All private records are synthetic. Native u0 uses the actual isolated publication
store; client reads use synthetic center replies. Audit guards reject production
paths, networking, private renderer reads/writes and SQL during rendering.

- default: all command modes and aliases × normal/u0 × OneBot/QQ.
- `--mode security`: real recorder identity/counts, hidden/self, unbound,
  pre/post-render and send revocation, send-failure fallback, member/order/profile changes.
- `--edges` (center): title overrides/order, three layouts, invalid layout,
  SQL failures and real pictures, including u0.
- `--faults`: frozen metric boundaries, >30 results, empty/countless data,
  missing current, rendering failures and excluded Bot mentions.
- `--representative`: short successful branch smoke.

`test_settings.py` migrates the original SELECT ordering/layout unit tests;
`test_cloud.py` migrates alias parsing tests. Evidence JSON contains only fixture
messages, image hashes/sizes and validation results. Large PNGs remain outside Git.
