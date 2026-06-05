<!--
Thanks for the PR.  Tick what applies, drop what doesn't.
Smaller PRs ship faster than big ones — please scope to a single
concern when you can.
-->

## What this change does

<!-- One paragraph.  Focus on intent, not the code diff. -->

## Why

<!-- Link to an issue, a discussion, or describe the user-facing
need that motivated this. -->

Closes #

## Type of change

- [ ] 🐞 Bug fix (no API change)
- [ ] ✨ New feature (non-breaking)
- [ ] 💥 Breaking change (API / CLI / config / image surface)
- [ ] 📖 Docs only
- [ ] 🧹 Refactor / cleanup
- [ ] ⚙️ Build / CI / tooling

## Checklist

- [ ] Tests added (or existing tests cover the change)
- [ ] Full test suite passes locally: `python -m pytest tests/ -q --ignore=tests/test_postgres_backend.py --ignore=tests/test_events_bus_redis.py`
- [ ] CHANGELOG.md updated under the relevant section (Added / Changed / Fixed / Removed)
- [ ] Documentation updated where user-facing behaviour changed
- [ ] If the change touches the Dockerfile or compose: smoke-tested the container boot + `/live` + `/ready`
- [ ] No credentials, customer data, or proprietary URLs in the diff

## Screenshots / output (optional)

<!-- Drop screenshots for UI changes, or paste sample output for
CLI / API changes.  Skip otherwise. -->

## Notes for reviewers

<!-- Anything reviewers should focus on, or anything you're unsure
about and want input on. -->
