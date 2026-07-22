# Spec Writing

Trellis specs are coding guidance for future agents. They should explain how to work in this repository, not how a generic project might be organized.

## Write From Evidence

Each important rule should be backed by one of these:

- A source file that demonstrates the preferred pattern.
- A test file that shows expected behavior.
- A project document that defines the convention.
- A repeated pattern across multiple files.

Use short snippets only when they make the rule clearer. Prefer linking to the file path and naming the symbol or behavior.

## File Structure

Keep the spec tree aligned with the project:

- Keep `index.md` as the navigation file for the spec directory.
- Split topics when developers would look for them independently.
- Merge topics when separate files would repeat the same rule.
- Delete template files that do not apply.
- Add new files for important local patterns the template missed.

## Content Standards

Good spec sections include:

- When the rule applies.
- The local pattern to follow.
- The source or test files that prove the pattern.
- Common mistakes or anti-patterns.
- Verification commands or checks when they are specific and reliable.

Avoid:

- Placeholder prose.
- Generic framework advice.
- Tool instructions that only work in one agent host.
- Long copied code blocks.
- Rules based on a single accidental implementation detail.

## Example Shape

```markdown
## Command Handlers

Command handlers should keep argument parsing, validation, and side effects separate. The local pattern is:

- Parse CLI flags at the command boundary.
- Convert raw inputs into typed task options before invoking core logic.
- Keep filesystem writes in the command or service layer, not in template helpers.

Reference files:
- `packages/cli/src/commands/example.ts`
- `packages/cli/test/commands/example.test.ts`

Avoid passing raw `process.argv` or unvalidated config objects into shared helpers.
```

## Final Pass

Before finishing:

```bash
grep -R "To be filled\\|TODO: fill\\|placeholder" .trellis/spec
```

Also check links, index files, and whether any spec still describes a template rather than this repository.
