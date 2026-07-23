# Contributing

Thanks for helping Product Demo Director make clearer, more truthful product films.

Please follow the [Code of Conduct](./CODE_OF_CONDUCT.md) in every project space. For a bug,
feature idea, or usage question, use the matching GitHub issue form. Search existing issues first,
and open an issue before investing in a large change so we can agree on scope.

Small fixes, focused tests, and documentation improvements are welcome without prior discussion.

## Set up a development checkout

```sh
git clone https://github.com/crimeacs/product-demo-director.git
cd product-demo-director
./pdd setup
./pdd doctor
./pdd test
```

Create a focused branch from `main`. The test command runs the Python suite and TypeScript checker;
FFmpeg, Python 3.10+, Node.js 18+, and npm are required. API keys are not needed for the regular
test suite.

## Make a focused change

- Keep behavior changes and refactors separate where practical.
- Add or update a focused `unittest` under `tests/` for pipeline changes.
- Update `README.md`, `SKILL.md`, or `docs/` when user-facing behavior changes.
- Preserve artifact hashes, exact-frame timing, claim evidence, and deterministic gates.
- Treat objective QA failures separately from subjective judge feedback.

For changes to the Remotion engine, run the TypeScript checker through `./pdd test`. For visual
changes, describe the project, exact render command, and QA result in the pull request. A small,
synthetic screenshot or proof sheet is preferable to source footage.

## Protect private data and provenance

Keep generated footage, narration, music, renders, and QA artifacts out of commits. Video and audio
formats are ignored by default; use `git add -f` only for a small, intentional, reviewed public
fixture.

Never commit API keys, `.env` files, customer identifiers, internal URLs, browser state, or
unredacted product footage. Before sharing logs or manifests, inspect them for local paths and
secrets. New third-party assets must have a redistribution-compatible license and an entry in
[`ASSET_PROVENANCE.md`](./ASSET_PROVENANCE.md).

If an AI agent materially contributed to a change, review the complete diff, tests, and asset
provenance yourself. The person opening the pull request remains responsible for the contribution.

## Pull requests

Before opening a pull request:

```sh
./pdd test
git diff --check
git status --short
```

Use the pull request template to explain the user-visible outcome, verification performed, and any
media or dependency implications. Maintainers may ask for a smaller patch or an additional
regression test. By submitting a contribution, you agree that it may be distributed under this
repository's [MIT License](./LICENSE).
