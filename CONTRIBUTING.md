# Contributing

Thanks for your interest in improving CrypTX. This guide covers how to set up a
development environment, the checks a change must pass, and how to submit it.

## Development setup

See the [Getting started](README.md#getting-started) section of the README for the
full local setup. In short:

```bash
# backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# frontend
cd ../frontend
npm install

# config
cd ..
cp .env.example .env      # set AUTH_SECRET at minimum
```

Run both servers with `./start.sh` (macOS / Linux) or `start.bat` (Windows).

## Before opening a pull request

Every change must pass the same checks CI runs:

```bash
cd backend && python -m pytest -v          # backend unit tests
python scripts/audit_tenant_isolation.py   # multi-tenancy isolation audit
cd ../frontend && npm run build            # typecheck + production build
```

If your change touches request handling or data access, confirm the
tenant-isolation audit does not report new unscoped queries.

## Guidelines

- **Keep pull requests focused.** One logical change per PR. Unrelated cleanups
  belong in their own PR.
- **Match the surrounding style.** Follow the conventions already in the file you
  are editing rather than introducing new ones.
- **Do not commit secrets or local data.** `.env`, `*.db`, `.auth_secret`,
  scraper caches, and build output are git-ignored and must stay that way. Never
  hardcode API keys.
- **Update docs with behaviour.** If you add configuration, an endpoint, or a
  feature, update the README and `.env.example` in the same PR.
- **New engine or router?** Add unit tests under `backend/tests/` and wire the
  router into `backend/main.py`.
- **Write clear commit messages.** A short imperative summary line, then a body
  explaining the why when it is not obvious.

## Reporting bugs

Open an issue with steps to reproduce, the expected and actual behaviour, and the
relevant chain, address type, or endpoint. Do not include private case data or
real API keys in issue text.

## Security

Report suspected vulnerabilities privately through a
[GitHub security advisory](https://github.com/Drvirus0x0FAC/Cryptx/security/advisories/new)
rather than a public issue.

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE).
