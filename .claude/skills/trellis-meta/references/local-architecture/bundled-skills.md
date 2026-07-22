# Bundled Skills

"Bundled skills" are multi-file built-in skills shipped inside the Trellis CLI npm package. Unlike marketplace skills (which a user installs separately into their own `.claude/skills/` or other platform skill root), bundled skills are written automatically into every supported platform's skill root by `trellis init` and kept in sync by `trellis update`. They are part of Trellis itself, not third-party content.

A bundled skill is a directory under `packages/cli/src/templates/common/bundled-skills/<skill>/` that already contains its own `SKILL.md` (with YAML frontmatter) plus optional `references/`, assets, or other supporting files. Trellis copies the whole directory tree as-is into each platform's skill root, so references stay lazy-loadable instead of being flattened into one oversized `SKILL.md`.

## What Counts As Bundled (vs. Adjacent Concepts)

| Source path | Type | How it ships |
| --- | --- | --- |
| `templates/common/bundled-skills/<name>/` | Bundled skill (multi-file) | Whole directory copied to every platform skill root |
| `templates/common/skills/<name>.md` | Single-file workflow skill | Wrapped with frontmatter, written as `<root>/<name>/SKILL.md` |
| `templates/common/commands/<name>.md` | Slash command / prompt | Written to each platform's command directory (`.claude/commands/trellis/`, `.cursor/commands/trellis-*.md`, `.gemini/commands/trellis/*.toml`, etc.) |
| `templates/<platform>/skills/` | Platform-specific skill | Written only into that platform's directory (e.g. `.codex/skills/`) |
| User skills under `.claude/skills/<my-skill>/` etc. | Marketplace or user-authored | Not managed by Trellis at all |

The Trellis CLI never touches anything that is not produced by one of its own template loaders. Anything a user drops into a platform skill root by hand is left alone.

## Current Bundled Skills (v0.6.0)

The set is discovered at runtime by listing directories under `templates/common/bundled-skills/`:

| Skill | Purpose |
| --- | --- |
| `trellis-meta` | This skill. Explains the local Trellis architecture and customization entry points to an AI working inside a user project. |
| `trellis-session-insight` | Wraps the `trellis mem` CLI so an AI knows when and how to reach into past Claude Code / Codex / Pi Agent conversation logs. |
| `trellis-spec-bootstrap` | Platform-neutral workflow for creating or refreshing `.trellis/spec/` from the real codebase (with optional GitNexus / ABCoder integration). |
| `trellis-channel` | Capability skill teaching an AI when to reach for `trellis channel` for multi-agent collaboration, forum/thread persistent boards, and dispatcher-wait patterns. |

The list is discovered at runtime, so adding a new directory under `bundled-skills/` is the only step required to register a new skill (see "Adding a New Bundled Skill" below).

## Where Bundled Skills Land Per Platform

Each platform configurator calls `writeSkills(<root>, <workflowSkills>, resolveBundledSkills(ctx))` during `trellis init`. `resolveBundledSkills` reads every directory under `templates/common/bundled-skills/`, resolves placeholders, and returns a flat list of `{relativePath, content}` entries. `writeSkills` then mirrors them under the platform's skill root.

| Platform | Bundled skill root | Notes |
| --- | --- | --- |
| Claude Code | `.claude/skills/<skill>/` | `configureClaude` |
| Cursor | `.cursor/skills/<skill>/` | `configureCursor` |
| Codex | `.agents/skills/<skill>/` | `configureCodex` writes the shared `.agents/skills/` root, which Gemini CLI 0.40+ also reads |
| Gemini CLI | `.agents/skills/<skill>/` | Same shared root as Codex; the two configurators are required to produce byte-identical output |
| Kiro | `.kiro/skills/<skill>/` | `configureKiro` (skills-based platform — no commands) |
| Qoder | `.qoder/skills/<skill>/` | `configureQoder` |
| Codebuddy | `.codebuddy/skills/<skill>/` | `configureCodebuddy` |
| Copilot | `.github/skills/<skill>/` | `configureCopilot` |
| Droid | `.factory/skills/<skill>/` | `configureDroid` |
| Antigravity | `.agent/skills/<skill>/` | `configureAntigravity` |
| Devin | `.devin/skills/<skill>/` | `configureDevin` |
| Kilo | `.kilocode/skills/<skill>/` | `configureKilo` |
| ZCode | `.zcode/skills/<skill>/` | `configureZcode` |
| OpenCode | (handled by `collectOpenCodeTemplates`) | Uses the same `resolveBundledSkills(ctx)` output |
| Pi, Reasonix | (their own collectors) | Same `resolveBundledSkills(ctx)` output |

Two paths exercise the same data:

1. `configureX(cwd)` writes files during `trellis init`.
2. `collectPlatformTemplates(platformId)` (in `configurators/index.ts`) returns a `Map<filePath, content>` that `trellis update` uses to detect drift and to populate `.trellis/.template-hashes.json`. Both must produce byte-identical output, so they both call `resolveBundledSkills(ctx)` and `collectSkillTemplates(root, …, resolveBundledSkills(ctx))`.

## Dispatch Wiring (Code Path)

The mechanism that auto-dispatches bundled skills to platform skill roots lives in two files:

1. `packages/cli/src/templates/common/index.ts`
   - `listDirectories("bundled-skills")` enumerates the on-disk skills.
   - `listBundledSkillFiles(skillDir)` walks each skill's directory recursively and returns `{relativePath, content}` for every file.
   - `getBundledSkillTemplates()` returns the cached `CommonBundledSkill[]`.

2. `packages/cli/src/configurators/shared.ts`
   - `resolveBundledSkills(ctx)` flattens that list into `ResolvedSkillFile[]` with `<skill>/<relativePath>` paths and resolved placeholders.
   - `writeSkills(skillsRoot, workflowSkills, bundledSkills)` writes both workflow skills and bundled skill files under `skillsRoot`.
   - `collectSkillTemplates(skillsRoot, workflowSkills, bundledSkills)` returns the same shape as a `Map<filePath, content>` for the update / hash pipeline.

Every platform configurator that supports skills imports both helpers (see `claude.ts`, `cursor.ts`, `codex.ts`, `gemini.ts`, `kiro.ts`, `qoder.ts`, `codebuddy.ts`, `copilot.ts`, `droid.ts`, `antigravity.ts`, `devin.ts`, `kilo.ts`). The `index.ts` `PLATFORM_FUNCTIONS` registry also calls `resolveBundledSkills(ctx)` inside each `collectTemplates` closure so `trellis update` tracking stays consistent.

## Adding a New Bundled Skill

The shape and dispatch wiring are already generic, so adding a skill requires only file changes plus distribution verification.

1. **Create the directory tree.**

   ```
   packages/cli/src/templates/common/bundled-skills/<my-skill>/
     SKILL.md                     # YAML frontmatter + body
     references/                  # optional
       <topic>.md
     assets/                      # optional (anything readable as utf-8)
   ```

2. **Write a valid `SKILL.md` header.** The frontmatter must include at minimum:

   ```yaml
   ---
   name: <my-skill>
   description: "When the AI should reach for this skill. Triggering phrases go here."
   ---
   ```

   The `description` is what each platform's auto-trigger mechanism matches against, so it should describe the user-intent triggers, not the skill's internals.

3. **Use placeholders where appropriate.** Bundled skill content runs through `resolvePlaceholders(file.content, ctx)`. Any `{{platform_name}}`, `{{python_cmd}}`, etc. token supported by `resolvePlaceholders` will be substituted per platform.

4. **No dispatch wiring is required.** `listDirectories("bundled-skills")` discovers the new directory automatically, so all platforms receive it on the next `trellis init` or `trellis update`.

5. **Verify the distribution path** before shipping. Skipping any of these steps has historically caused features to be documented as bundled while the published npm tarball was missing the files:

   - Source files exist on the branch being tagged.
   - `pnpm --filter @mindfoldhq/trellis build` copies the asset into `dist/templates/common/bundled-skills/<skill>/`.
   - `npm pack --dry-run --json` includes the expected `dist/**` paths.
   - In a fresh temp project, `trellis init` writes `.claude/skills/<skill>/SKILL.md`, `.agents/skills/<skill>/SKILL.md`, `.zcode/skills/<skill>/SKILL.md`, etc.
   - `.trellis/.template-hashes.json` lists the generated files.
   - `trellis update --dry-run` in that temp project reports "Already up to date!".

6. **Add a migration manifest entry** if the skill is added in a release that other projects will upgrade into. Without an explicit manifest entry the file will land via the standard "missing file" branch of `trellis update`, but a manifest makes the change visible in the changelog.

## Overriding a Bundled Skill Locally

There is no formal "project-local skill" mechanism (e.g. `.trellis/skills/`). Bundled skills are platform-rooted, so any override is platform-rooted too.

The supported pattern relies on the existing template-hash diff in `trellis update`:

1. Edit the local file directly. Example: `.claude/skills/trellis-meta/SKILL.md`.
2. The file's hash now diverges from the entry in `.trellis/.template-hashes.json`.
3. The next `trellis update` detects the user modification and leaves the file untouched (Trellis never overwrites user-modified files without an explicit `--force`).

Caveats:

- The override only applies to the one platform whose directory you edited. To override the same skill across, for example, Claude Code and Codex, you must edit both `.claude/skills/<name>/` and `.agents/skills/<name>/`.
- A future `trellis update --force` will overwrite local edits. Keep the override under version control so it can be reapplied if needed.
- Marketplace skills installed under the same platform skill root with a different folder name (e.g. `.claude/skills/my-custom-meta/`) are untouched by Trellis and are the cleaner option when the goal is to add behavior, not to mutate the bundled skill.
- Team-private conventions belong in `.trellis/spec/` or in a separate marketplace-style local skill, not in modifications to `trellis-meta` itself. See `customize-local/add-project-local-conventions.md`.

## Removing a Bundled Skill From a Project

There is no per-project opt-out flag for bundled skills. Two options:

1. **Delete the directory in each platform skill root.** `trellis update` will see the file missing, compare against `.template-hashes.json`, and treat the deletion the same as any other user modification — it will not silently re-create the directory unless `--force` is passed.

2. **Pin a Trellis version that did not ship the skill.** The bundled-skill set is determined at build time, so installing an older release of the CLI is the only way to permanently exclude a skill that the current release ships.

A third option — globally disabling all bundled skills — is not supported. The dispatch is unconditional in every configurator. Adding such a flag would require changing `PLATFORM_FUNCTIONS` in `configurators/index.ts` and every `configureX` function.

## Operating Rules

- Treat `templates/common/bundled-skills/` as the single source of truth for what bundled skills exist. Do not hand-maintain platform-by-platform skill lists.
- Do not add platform-specific logic inside a bundled `SKILL.md`. If a behavior is platform-specific, put it in `templates/<platform>/skills/` instead.
- Do not couple bundled skills to a specific CLI binary (e.g. `trellis mem`) without surfacing the dependency in the skill's description and references — users on older releases may not have the command.
- Do not store project-private content in a bundled skill. Bundled skills are public, shipped to every user; project rules belong in `.trellis/spec/` or a local skill.
