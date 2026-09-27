# Studio motion study

A 26.5-second executable study of the engine's studio direction: masked headline reveals,
dimensional product staging, a camera arrival onto the edit timeline, an attached annotation,
a quiet proof hold, and one resolved ending. It uses the explicitly labeled curated workbench
replay from the repository announcement. It does not claim to record a proprietary agent interface.

The script contains no generated narration and needs no model calls. The soundtrack used in the
local reference render is the existing announcement music; it is optional. Three editorial accents
are synthesized deterministically by the builder. These are graphic cues, not recorded product audio.

From the repository root, first generate the workbench footage using the commands in
[`../save-the-cat/assets/README.md`](../save-the-cat/assets/README.md), then:

```sh
mkdir -p examples/studio/assets examples/studio/_src
cp examples/save-the-cat/assets/codex-workbench.webm examples/studio/assets/
cp examples/save-the-cat/_src/codex-workbench.json examples/studio/_src/
# Optional: use your existing, licensed music bed.
# cp examples/save-the-cat/music.mp3 examples/studio/music.mp3
python3 tools/build.py --project examples/studio --contracts strict
python3 tools/finish.py --input examples/studio/out/demo.mp4 \
  --out examples/studio/out/demo-final.mp4 --require-artifact
python3 tools/qa.py --video examples/studio/out/demo-final.mp4 \
  --project examples/studio --require-artifact --strict
./pdd review examples/studio --serve
```

The long quiet intervals without the optional music are intentional; strict silence QA may report
them. For the complete music-led study, provide a bed. See [studio direction](../../docs/STUDIO_DIRECTION.md)
for the authoring grammar. Source-space coordinates in this example were checked against the
1920×1080 workbench replay. New recordings with different layouts need fresh inspection.
