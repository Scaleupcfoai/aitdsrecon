## /finish — End of Session Protocol

You are wrapping up a Claude Code session. Do the following **before** the session ends:

### Step 1: Summarize what was done

List the key changes made this session in 2-5 bullets. Be specific — mention file names, modules, and business logic affected.

### Step 2: Update CHANGELOG.md

1. **Unreleased section:** Add each change under the correct category (Added / Changed / Fixed).
2. **Session Log table:** Add a new row at the top with today's date, a one-line summary, files touched, and the version.
3. **Current State block:** Update:
   - `Version` — bump if appropriate (patch for fixes, minor for features).
   - `Status` — what state is the project in now?
   - `Last session` — today's date.
   - `Next priority` — what should the next session focus on?
4. **Known Issues:** Add anything unresolved or partially done.

### Step 3: Version bump decision

- Did you only fix bugs or add tests? → Bump PATCH (e.g., 0.1.0 → 0.1.1)
- Did you add a new feature or module? → Bump MINOR (e.g., 0.1.1 → 0.2.0)
- Did you change the API contract, data model, or matching engine interface? → Bump MAJOR
- Only config or docs changes? → No bump needed, just log the session.

### Step 4: Git commit (if git is initialized)

Stage and commit with a message following this format:

```
v{VERSION}: {one-line summary}

- {bullet 1}
- {bullet 2}
- {bullet 3}

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

### Step 5: Confirm with the user

Tell Ashish:
- What version we're now at
- What was done
- What the suggested next session should focus on
