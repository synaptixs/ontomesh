# Security policy

Thank you for taking the time to disclose a security issue responsibly.

## Supported versions

| Version | Supported |
|---|---|
| 3.x | ✅ Best-effort security fixes on the latest minor |
| < 3.0 | ❌ No longer supported |

The "supported" version is defined as the latest published GitHub release.  Pre-release tags (`*-dev`) are tracked but not maintained for security patches.

## Reporting a vulnerability

**Do not open a public issue for vulnerabilities.**  Use one of the following private channels:

1. **GitHub Security Advisories** (preferred).  Open a [draft advisory](https://github.com/synaptixs/ontomesh/security/advisories/new) on the repository.  We get an automatic notification and can collaborate on a fix privately.
2. **Email.**  If you can't use GitHub Advisories, send the details to **security@synaptixs.dev** (replace once a real address exists).  Include:
   - A description of the vulnerability and its impact.
   - Steps to reproduce, including image tag / version / commit SHA.
   - Any proof-of-concept code.
   - Your preferred name + contact for credit in the eventual advisory (or "anonymous" if you prefer).

## What to expect after you report

- **Acknowledgement**: within **3 working days**.
- **Initial triage**: within **7 working days** — we'll confirm whether the report is in scope and (if so) give you a rough timeline.
- **Fix + advisory**: typical 30–60 days from confirmation, depending on severity.  Critical issues are handled faster.
- **Disclosure**: we publish a GitHub Security Advisory + CHANGELOG entry once the fix is available.  We will credit you unless you ask us not to.

## What's in scope

- The published container image at `ghcr.io/synaptixs/ontomesh:*`.
- The source code in this repository.
- The Python package distributed as `ontomesh` (when published).

## What's out of scope

- Vulnerabilities in third-party dependencies — please report those upstream.  We'll bump the dependency once they release a fix.
- Social-engineering, phishing, or physical-access scenarios.
- Denial-of-service via resource exhaustion in user-supplied input (e.g. a 10 GB log file slows the wizard).
- Bugs in deprecated / unsupported versions.

## Safe harbour

We will not pursue legal action against researchers who:

- Make a good-faith effort to disclose privately first.
- Don't access data beyond what's necessary to demonstrate the vulnerability.
- Don't degrade availability or destroy data.
- Give us a reasonable window to fix the issue before going public (typically 90 days).

Thank you for keeping the project — and its users — safe.
