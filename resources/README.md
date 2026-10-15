# Private runtime resources

`deployment-manifest.json` owns exact relative deployment paths, sizes and SHA256
values. Rights-unverified content belongs in a separate private store, never the public
wheel or Git repository. The current store has no remote backup; its operator must
preserve it independently of Sakura source checkout cleanup.

An authorized future operator can verify an explicitly selected store with:

```sh
python -m taiko_bot.cli.resources verify --manifest deployment-manifest.json --store /private/taiko-resources
```

To provision a new directory, use `materialize` with an explicit `--destination`.
The CLI checks every source before writing, rejects path traversal/symlinks and differing
existing files, and installs verified files without replacing a racing writer's file.
Identical files are reused. It performs no downloads, OSS operations or secret discovery.
Production materialization was not performed for this release.

No redistribution license is inferred from a file being tracked. Ten historical samples
are listed under `held`; their contents were not read. `ownership-inventory.json` lists
all remaining Sakura paths, including the uninspected workbook and historical output.
