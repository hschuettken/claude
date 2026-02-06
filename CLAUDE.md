# CLAUDE.md

This file provides guidance for AI assistants working with this repository.

## Project Overview

This is the **claude** project — a newly initialized repository. The codebase is in its early stages; structure and tooling will evolve as development progresses.

- **Repository**: `hschuettken/claude`
- **Primary branch**: `main` (or as configured by the remote)

## Repository Structure

```
/
├── README.md          # Project readme
└── CLAUDE.md          # This file — guidance for AI assistants
```

> Update this section as new directories and files are added (e.g., `src/`, `tests/`, `docs/`, config files).

## Development Setup

No build system, package manager, or dependencies have been configured yet. When they are added, document the following here:

- **Language(s)**: _TBD_
- **Package manager**: _TBD_ (e.g., npm, pip, cargo)
- **Install dependencies**: _TBD_ (e.g., `npm install`)
- **Build command**: _TBD_ (e.g., `npm run build`)
- **Run command**: _TBD_ (e.g., `npm start`)

## Testing

No test framework has been configured yet. When one is added, document:

- **Test command**: _TBD_ (e.g., `npm test`)
- **Test directory**: _TBD_ (e.g., `tests/`)
- **Single test**: _TBD_ (e.g., `npm test -- --grep "test name"`)

## Linting and Formatting

No linter or formatter has been configured yet. When added, document:

- **Lint command**: _TBD_ (e.g., `npm run lint`)
- **Format command**: _TBD_ (e.g., `npm run format`)
- **Config files**: _TBD_ (e.g., `.eslintrc`, `.prettierrc`)

## Code Conventions

As the project develops, document coding conventions here:

- **Style guide**: _TBD_
- **Naming conventions**: _TBD_
- **File organization**: _TBD_
- **Error handling patterns**: _TBD_

## Git Workflow

- Write clear, descriptive commit messages focused on the "why" rather than the "what"
- Keep commits atomic — one logical change per commit
- Do not commit files containing secrets (`.env`, credentials, API keys)

## Key Notes for AI Assistants

1. **Read before modifying** — Always read a file before proposing changes to it.
2. **Minimal changes** — Only make changes that are directly requested or clearly necessary. Avoid over-engineering.
3. **No guessing** — If the project structure or conventions are unclear, explore the codebase first rather than making assumptions.
4. **Update this file** — When you add significant tooling, dependencies, or architectural decisions, update this CLAUDE.md to reflect the current state.
5. **Security** — Never commit secrets or credentials. Be cautious of command injection, XSS, SQL injection, and other vulnerabilities.
