# Contributing to VOIA

Thanks for helping build an open voice-agent OS. VOIA is **open-core**: the self-hosted platform is MIT; managed cloud convenience may be commercial — see [docs/OPEN_CORE.md](docs/OPEN_CORE.md).

Upstream streaming primitives live in `vocode/` (Vocode). Most product work lands in `voice_platform/` and `frontend/`.

## Quick setup

1. Follow **Tier 0** in the root [README](README.md) (`docker compose --profile playground up -d` + `ALLOW_DEV_LOGIN=true` + one LLM key).
2. Run `python3 scripts/check_setup.py` until it reports ready for playground.
3. Optional: `poetry install` and `cd frontend && npm install` for non-Docker work.

## Development norms

- Prefer small, focused PRs (one seam: provider, node, template, or bugfix).
- Do not commit `.env`, real API keys, or customer PII.
- Customer-shaped demo ops scripts belong under `examples/` (see `examples/smilecare/`), not the default onboarding path.
- Keep **playground ↔ live** flow semantics aligned when you touch `voice_platform/flow/` or `agents/flow_agent.py`.

## Extension points

| You want to add… | Guide | Code seams |
|------------------|-------|------------|
| LLM / STT / TTS provider | [docs/extensions/add-provider.md](docs/extensions/add-provider.md) | `agent_factory.py`, Vocode adapters, key routes |
| Flow node type | [docs/extensions/add-node.md](docs/extensions/add-node.md) | `flow/nodes.py`, `WorkflowNodes.tsx`, graph contracts |
| Integration action | (see add-node action path) | `voice_platform/integrations/`, workflow executor |
| Template | [docs/extensions/add-template.md](docs/extensions/add-template.md) | `agent_templates.py`, `examples/` |

Also: [docs/MOAT.md](docs/MOAT.md), [docs/VOIA_ARCHITECTURE_AND_QUICKSTART.md](docs/VOIA_ARCHITECTURE_AND_QUICKSTART.md).

## Lint, types, tests

```bash
poetry install
make test-fast          # contributor default
make setup-check
make lint_diff          # if Makefile targets apply
make typecheck_diff     # vocode/ typing where enforced

cd frontend && npm install && npx tsc --noEmit
```

Pre-commit (optional but welcome):

```bash
brew install pre-commit   # or pipx
poetry run pre-commit install
```

## PR checklist

- [ ] Tier affected documented (0 / 1 / 2) if you change setup or keys
- [ ] Tests or a clear manual repro for behavior changes
- [ ] No secrets; SmileCare/UMT fixtures stay in `examples/` unless anonymized
- [ ] README / `.env.example` updated when adding required config

## Issues

Use GitHub Issues on this repository. Label suggestions: `good first issue`, `provider`, `flow-node`, `docs`, `bug`.

## License

By contributing, you agree your contributions are licensed under the MIT License (see [LICENSE](LICENSE) and [NOTICE](NOTICE)).
