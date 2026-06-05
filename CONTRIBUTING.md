# Contributing to Ontomesh

Thank you for your interest in contributing. This guide explains how to submit issues, propose changes, and have code merged — and the conduct we expect from everyone involved.

---

## Table of Contents

1. [Code of Conduct](#1-code-of-conduct)
2. [Who can contribute](#2-who-can-contribute)
3. [Reporting bugs and requesting features](#3-reporting-bugs-and-requesting-features)
4. [Setting up a development environment](#4-setting-up-a-development-environment)
5. [Branching strategy](#5-branching-strategy)
6. [Making changes](#6-making-changes)
7. [Submitting a pull request](#7-submitting-a-pull-request)
8. [Review process](#8-review-process)
9. [Coding standards](#9-coding-standards)
10. [Adding or modifying industry templates](#10-adding-or-modifying-industry-templates)
11. [Commit message format](#11-commit-message-format)
12. [Enforcement and contact](#12-enforcement-and-contact)

---

## 1. Code of Conduct

This project follows the **[Contributor Covenant 2.1](CODE_OF_CONDUCT.md)**.  By participating, you agree to abide by its terms.

In short:

- Be welcoming and respectful.  Critique the work, not the person.
- Assume good intent; ask for clarification before assuming malice.
- No harassment, doxing, sustained disruption, or claiming credit for others' work.

Report conduct violations privately by opening a [draft Security Advisory](https://github.com/synaptixs/ontomesh/security/advisories/new) (yes, the same channel as security disclosures — it's the only private channel GitHub gives us).  Retaliation against reporters is itself a violation.

---

## 2. Who can contribute

| Contributor type | Access | Workflow |
|---|---|---|
| **Internal** (team member with write access) | Can push feature branches directly to the repository | Branch → PR → review → merge to `develop` |
| **External** (anyone else) | Read-only access to the repository | Fork → branch → PR against `develop` |

Both paths go through the same pull-request review gate before anything reaches `develop` or `main`.

---

## 3. Reporting bugs and requesting features

Use GitHub Issues for all bug reports and feature requests.

### Reporting a bug

1. Search existing issues first — your bug may already be tracked.
2. Open a new issue and select the **Bug report** template.
3. Include at minimum:
   - A clear, descriptive title.
   - Steps to reproduce (commands run, input files if relevant).
   - Expected behaviour vs. actual behaviour.
   - Python version, OS, and conda env name (run `conda info` and `python --version`).
   - Relevant error output or stack trace (use a code block).

### Requesting a feature or new industry template

1. Open a new issue and select the **Feature request** template.
2. Describe the use case — *why* is this needed, not just what.
3. If proposing a new industry template, name the domain, the external standards it aligns to, and the entities you expect.
4. Maintainers will label the issue and discuss scope before any work begins.

### Security vulnerabilities

Do **not** open a public issue for a security vulnerability. Email the maintainers directly (see §12). We follow a 90-day responsible-disclosure window.

---

## 4. Setting up a development environment

**Prerequisites:** Git, [Miniconda or Anaconda](https://docs.conda.io/), Python 3.12.

```bash
# 1. Clone the repository (external contributors: fork first, then clone your fork)
git clone https://github.com/synaptixs/ontomesh.git
cd ontomesh

# 2. Create the conda environment
conda create -n ontology python=3.12 -y
conda activate ontology

# 3. Install all dependencies
pip install -r requirements.txt

# 4. (Optional) Install spaCy language model for log entity discovery
python -m spacy download en_core_web_sm

# 5. Verify the full pipeline runs cleanly
python toolkit.py --phase all
```

The pipeline should complete with `✓ Pipeline complete` and no `ERROR` lines.

---

## 5. Branching strategy

```
main          ← stable releases only; protected, no direct pushes
develop       ← integration branch; all PRs target this
feature/xyz   ← short-lived feature branches off develop
fix/xyz       ← bug fix branches off develop
template/xyz  ← new industry template branches off develop
```

Branch naming rules:
- Use lowercase with hyphens: `feature/drift-alert-export`, `fix/shacl-severity-typo`.
- Prefix with the type: `feature/`, `fix/`, `template/`, `docs/`, `chore/`.
- Keep branches focused — one logical change per branch.
- Delete merged branches promptly (see §7).

**Internal contributors** create branches directly in the main repository.  
**External contributors** create branches in their fork.

---

## 6. Making changes

1. Create your branch from the latest `develop`:
   ```bash
   git checkout develop
   git pull origin develop          # or: git pull upstream develop (fork workflow)
   git checkout -b feature/your-feature-name
   ```

2. Make your changes. Run the relevant phase to confirm nothing is broken:
   ```bash
   python toolkit.py --phase all
   ```

3. Run the test suite (if tests exist for your area):
   ```bash
   pytest tests/ -v
   ```

4. For changes to SHACL shapes or OWL modules, confirm SHACL validation still passes:
   ```bash
   python toolkit.py --phase 3   # SHACL shape generation
   ```

5. For new or modified industry templates, validate the YAML parses and generates correctly:
   ```bash
   python toolkit.py --phase templates --template your_template_name
   ```

---

## 7. Submitting a pull request

### Before opening the PR

- [ ] The full pipeline (`--phase all`) runs without `ERROR`.
- [ ] `pytest tests/` passes (or confirm which tests are not yet written and why).
- [ ] No secrets, credentials, or personal data in any committed file.
- [ ] `requirements.txt` updated if you added a new dependency.
- [ ] Commit messages follow the format in §11.

### Opening the PR

1. Push your branch:
   ```bash
   git push origin feature/your-feature-name
   ```
2. Open a pull request on GitHub targeting the `develop` branch.
3. Fill in the PR template completely:
   - **Summary** — what the change does and why.
   - **Test plan** — how you verified it works.
   - **Related issues** — link with `Closes #NNN` to auto-close on merge.
4. Request at least one reviewer. Internal contributors should request the code owner for the affected module. External contributors may leave reviewer selection to maintainers.

### External contributor fork workflow

```bash
# Add the upstream remote once
git remote add upstream https://github.com/synaptixs/ontomesh.git

# Keep your fork's develop in sync before starting work
git fetch upstream
git checkout develop
git merge upstream/develop
```

### After the PR is merged

Delete your branch:
```bash
git push origin --delete feature/your-feature-name   # remote
git branch -d feature/your-feature-name              # local
```

---

## 8. Review process

| Step | Who | Expected timeframe |
|---|---|---|
| Automated checks (lint, pipeline smoke test) | CI | Immediate |
| First human review | Assigned reviewer | 2 business days |
| Author addresses feedback | Contributor | No fixed deadline, but stale PRs (>30 days with no activity) may be closed |
| Final approval + merge | Maintainer | 1 business day after approval |

**Review guidelines for reviewers:**
- Be specific — point to the exact line and explain what to change and why.
- Distinguish blocking feedback (must fix) from suggestions (nice to have) using the GitHub review conventions: `Request changes` vs. `Comment`.
- Do not approve if the pipeline or tests fail.

**Guidelines for contributors receiving review:**
- Respond to every comment, even if just to acknowledge.
- If you disagree with feedback, explain your reasoning — don't silently ignore it.
- Push fixes as new commits during review; squash only when instructed by the reviewer.

---

## 9. Coding standards

### Python

- Python 3.12+. All new modules must be importable under the conda `ontology` environment.
- Follow [PEP 8](https://peps.python.org/pep-0008/). Maximum line length: 120 characters.
- Type hints are encouraged for all public functions.
- Entry-point pattern: every new source module must expose a `run_<module>(out_path, ...)` function that matches the conventions in `toolkit.py`.
- No new `print()` calls in library code — use the `step()` / `print("  ✓ ...")` convention already established in the pipeline.
- Avoid adding dependencies to `requirements.txt` without discussion. Prefer the standard library where possible.

### Ontology / RDF

- All OWL Turtle files use the `BASE_IRI = "https://ontology.example.com/enterprise/"` prefix convention already established in the codebase.
- Every new OWL class must declare at minimum: `a owl:Class`, `rdfs:label`, `rdfs:comment`, `:sensitivityTier`.
- Every new SHACL NodeShape must declare a severity (`sh:Violation` or `sh:Warning`) and a human-readable `sh:message`.
- Do not introduce `rdflib` or `pyshacl` as a hard runtime dependency in core pipeline modules — the pipeline is designed to run without them for portability.

### YAML templates

- Follow the structure in `templates/pharmaceuticals.yaml` as the canonical reference.
- Every entity must include: `name`, `label`, `description`, `sensitivity`, and at least one property.
- Properties must use the list-of-dicts format: `- prop_name: {type: string, required: true}`.
- Templates must include at least 8 entities, 3 events, and 8 competency questions with assigned priorities.

---

## 10. Adding or modifying industry templates

New industry templates are especially welcome. Follow these steps:

1. Create `templates/<domain_name>.yaml` using `templates/pharmaceuticals.yaml` as the reference.
2. Ensure the file passes `yaml.safe_load` without errors:
   ```bash
   python -c "import yaml; yaml.safe_load(open('templates/your_template.yaml'))"
   ```
3. Run the template generator and confirm OWL and CQ artifacts are produced:
   ```bash
   python toolkit.py --phase templates --template your_template_name
   ```
4. Check `output/ontology/your_template_name.ttl` and `output/reports/cq_your_template_name.csv` are well-formed.
5. Add the template name to `BUILTIN_TEMPLATES` in `src/template_loader.py` and the template list in `wizard/app.py`.
6. Document the external standard alignments in the PR description.

---

## 11. Commit message format

```
<type>(<scope>): <short summary in present tense, ≤72 chars>

<optional body — explain WHY, not what. Reference issues with #NNN>

Co-Authored-By: Your Name <email@example.com>
```

**Type values:**

| Type | When to use |
|---|---|
| `feat` | New feature or new module |
| `fix` | Bug fix |
| `template` | New or updated industry template |
| `docs` | Documentation only (README, CONTRIBUTING, etc.) |
| `test` | Adding or fixing tests |
| `chore` | Build, CI, dependency, or tooling changes |
| `refactor` | Code change that neither fixes a bug nor adds a feature |

**Examples:**

```
feat(tmf630): add TmfTask async resource + bulk import/export

Implements TMF630 Parts 4 and 7. Adds TmfTask, TmfImportJob, and
TmfExportJob OWL classes, SQLite tables, MCP tool definitions, and
three CQ tests. Closes #42.
```

```
fix(template_loader): handle list-of-dicts YAML property format

PyYAML loads YAML block sequences as list, not dict. _iter_properties()
now handles both formats so templates with - prop: {type: string} syntax
parse correctly. Closes #51.
```

---

## 12. Enforcement and contact

Maintainers are responsible for enforcing this guide and the code of conduct fairly and consistently.

**Actions available to maintainers** in response to violations, in escalating order:
1. Private written warning explaining the violation.
2. Temporary suspension from contributing (duration at maintainer discretion).
3. Permanent ban from the project.

**Contact the maintainers:**

Open a [GitHub Discussion](https://github.com/synaptixs/ontomesh/discussions) for general questions.
For conduct violations or security issues, see [`SECURITY.md`](SECURITY.md) for the disclosure process.

---

*This document is itself subject to contribution — if something is unclear or missing, open an issue or PR against `CONTRIBUTING.md`.*
