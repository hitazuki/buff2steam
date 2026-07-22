# Repository instructions

## Commit conventions

All commits must use Conventional Commits with a required scope:

```text
<type>(<scope>): <description>
```

Allowed types are `feat`, `fix`, `docs`, `refactor`, `perf`, `test`, `build`,
`ci`, `chore`, and `revert`.

- Use a lowercase kebab-case scope, such as `rules`, `quote`, `smis-client`, or
  `astrbot-plugin`.
- Write a concise description after the colon and space.
- Add `!` before the colon for a breaking change, for example
  `feat(api)!: replace subscription endpoints with rules`.
- Apply the same format to pull request titles because squash merges use the
  pull request title as the resulting commit subject.

Examples:

- `feat(rules): update duplicate rule threshold`
- `fix(quote): mark the lowest platform price`
- `docs(deploy): clarify VPS deployment steps`
- `test(rules): cover duplicate rule consolidation`

Before creating a commit, validate its subject with:

```text
python scripts/check_commit_message.py --message "feat(scope): description"
```
