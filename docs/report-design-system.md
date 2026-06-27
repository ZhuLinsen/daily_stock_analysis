# Report design system

DSA now has a root `DESIGN.md` contract for generated report artifacts. It is a source-readable design-system file for agents and generators that produce Ben-facing dashboards, PDFs, PNG exports, and compact cards.

## Consumers

- Report and PDF generators should read `DESIGN.md` before changing layout, typography, card hierarchy, colors, or chart presentation.
- Card and PNG generators should use the same semantic color and spacing rules so screenshots, cards, and PDFs do not drift into separate visual systems.
- Agents should treat the YAML front matter as the normative token source and the Markdown body as usage guidance.
- Generated Ben-facing artifacts should default to English-only output and avoid CJK text unless a request explicitly overrides the language.

## Local tool wiring

The DESIGN.md CLI is pinned under `tools/design-md/` so checks do not depend on a flaky one-shot `npx` download.

Install the local toolchain:

```bash
npm install --prefix tools/design-md --no-audit --ignore-scripts
```

Run the checks used by the design contract canary:

```bash
tools/design-md/node_modules/.bin/designmd lint DESIGN.md
tools/design-md/node_modules/.bin/designmd export --format dtcg DESIGN.md > /tmp/dsa-design-dtcg.json
tools/design-md/node_modules/.bin/designmd export --format css-tailwind DESIGN.md > /tmp/dsa-design-theme.css
```

Regenerate the checked-in machine-consumable artifacts:

```bash
npm run --prefix tools/design-md generate
```

The checked-in `design-tokens.json` file is the DTCG export for token consumers that can ingest W3C-style design tokens. The checked-in `design-theme.css` file is a normalized Tailwind v4 `@theme` block that downstream UI or artifact renderers can adapt in a later integration slice.

## Rollback

This slice is source-only. To roll back, revert:

- `DESIGN.md`
- `tools/design-md/package.json`
- `tools/design-md/package-lock.json`
- `tools/design-md/.gitignore`
- `tools/design-md/trim-trailing-blank-lines.mjs`
- `design-tokens.json`
- `design-theme.css`
- `docs/report-design-system.md`
- the matching `docs/CHANGELOG.md` entry

No service restart, deployment, database migration, runtime config change, or notification send is required.

## Follow-up integration

Future slices can wire the exported tokens into:

1. PDF/report templates for typography, spacing, and card hierarchy.
2. PNG/card renderers for mobile-scannable analyst summaries.
3. Web report surfaces where existing Tailwind/CSS variables can map to the contract.
4. Agent prompts that need a stable visual authority before generating or reviewing report artifacts.

Each integration should keep generated artifacts English-only by default for Ben-facing output, preserve semantic signal colors, and add focused visual proof such as before/after screenshots or exported sample PDFs when the renderer changes.
