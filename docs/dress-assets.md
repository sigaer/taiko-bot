# Official costume resources

`assets/dress/catalog.json` is the authoritative map from game costume IDs to
local layers, palettes, outlines, paint adaptations and z indices. Center and
client personal displays use `runtime/player/dress_renderer.py`; offline
displays use the same compositor. Rendering performs no network requests.

Import a new mini-program archive into a disk-backed staging directory:

```sh
bash /home/sigaer/taiko/taiko-forum/scripts/memory/run_qa.sh \
  /usr/bin/python3 -m taiko_bot.offline.dress_import INPUT.zip /var/tmp/taiko-dress-stage --download
```

Run this from the source repository. The importer decrypts the wxapkg and parses
only the costume module's data expressions; it never executes JavaScript. It
downloads at most four images concurrently, validates PNGs and retains a URL
cache for interrupted runs. The staged `dress/catalog.json` is published only
after every reference succeeds. Download plans, checksums and errors stay next
to the staged directory, outside production resources.

Main files retain `cos/cos_290_NNN.png`, `head/head_290_NNN.png`,
`body/body_290_NNN.png`, `paint/paint_290_NNN.png` and
`accessories/accF_290_NNN.png`, using the **game ID**, not the URL suffix. For
example, accessory 106 uses remote image 125, and accessory 188 uses image 005.
The level variants of costume 36 retain their filenames and explicit level map,
including level zero. Additional palette assets live under `special/`; icons
live under `icons/`. Keep the catalog with the images when distributing assets.

Package 40's body 144 references a nonexistent main image and incorrectly
borrows balloon-head 144 palettes (including 63 nonexistent URLs) and sword-body
136 skin. These unrelated overlays produce floating faces on the spear/armor
body. `offline/dress_import/corrections.py` uses its existing standard body
image and normal base layers. Corrections are recorded in the catalog. Future
unknown failures stop import for review.

Verify the staged catalog with `scripts/readiness/check-dress-catalog.py` under
the QA wrapper. It checks every referenced PNG, renders every costume, every
special palette index, head-adapted paints and every supported dan level, and
writes a contact sheet using synthetic profiles. Keep user/history data out of QA.

After validation, merge the staged resources into the production dress directory
with a backup of changed files and publish the catalog last. Preserve unrelated
historical resources. Rebuild the existing dress archive and total asset bundle,
then verify the Viewer manifest and download endpoint before deploying the Bot
with the standard installed-release script. No Viewer API change is required.

## Official title plates

The title catalog refresh updates names and conditions; nameplate images are separate resources. Import the mini-program title mapping as well when its plates change:

```sh
bash /home/sigaer/taiko/taiko-forum/scripts/memory/run_qa.sh \
  /opt/taiko-bot/current/bin/python -I -m taiko_bot.offline.nameplate_import \
  INPUT.zip /var/tmp/taiko-nameplate-stage \
  --missing-from /home/sigaer/taiko/assets/name_plate --download
```

The importer stages both ordinary and dan variants using game IDs, including plates that share one remote image. It parses data without executing JavaScript, downloads at most four images concurrently, verifies bounded PNGs, and refuses to overwrite staged files. Review the staged images and report, then copy only verified missing files to `assets/name_plate`. Keep private assets and import reports outside Git.

Rebuild the nameplate archive and total bundle with `scripts/build_open_resource_archives.sh nameplate` under the bounded build wrapper, then verify the Viewer manifest and bundle endpoints. This scope preserves the other individual resource archives. All supported plate IDs should render in both ordinary and dan layouts; use synthetic profiles for rendering checks.
