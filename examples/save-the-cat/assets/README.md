# Reproducible repo-native footage

This film is about Product Demo Director itself. Its source surfaces come from committed JSON
transcripts of the repository and its real production commands—there is no unrelated product or
funnel fixture. Generated video files remain ignored by Git.

From the repository root:

```sh
.venv/bin/python tools/term.py \
  --project examples/save-the-cat \
  --name pdd-raw-terminal \
  --title "raw recording — product-demo-director" \
  --transcript examples/save-the-cat/_src/pdd-raw-terminal.json \
  --out examples/save-the-cat/assets/pdd-raw.webm

.venv/bin/python tools/term.py \
  --project examples/save-the-cat \
  --name pdd-directed-terminal \
  --title "Codex — product-demo-director" \
  --transcript examples/save-the-cat/_src/pdd-directed-terminal.json \
  --out examples/save-the-cat/assets/pdd-directed.webm

.venv/bin/python tools/workbench.py \
  --project examples/save-the-cat \
  --session examples/save-the-cat/_src/codex-workbench.json \
  --out examples/save-the-cat/assets/codex-workbench.webm

.venv/bin/python tools/term.py \
  --project examples/save-the-cat \
  --name pdd-release-terminal \
  --title "open source — product-demo-director" \
  --transcript examples/save-the-cat/_src/pdd-release-terminal.json \
  --out examples/save-the-cat/assets/pdd-release.webm
```

The terminal and workbench footage are disclosed curated replays: the prompts, commands, files, and
delivery targets are whitelisted in source JSON and the final values are checked against strict QA.
They are semantically reproducible; browser and WebM encoders are not guaranteed to produce
bit-identical binaries across machines, so the evidence receipt binds the published reference assets.
They do not imitate or claim to capture a proprietary Codex or Claude interface.

Both recorders use Playwright Chromium when installed and otherwise discover local Chrome,
Chromium, or Edge. Set `PDD_BROWSER_EXECUTABLE` to override discovery.
