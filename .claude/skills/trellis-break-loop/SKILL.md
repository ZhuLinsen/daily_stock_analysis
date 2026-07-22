---
name: trellis-break-loop
description: "Deep bug analysis to break the fix-forget-repeat cycle. Analyzes root cause category, why fixes failed, prevention mechanisms, and captures knowledge into specs. Use after fixing a bug to prevent the same class of bugs."
---

# Break the Loop - Deep Bug Analysis

When debug is complete, use this for deep analysis to break the "fix bug -> forget -> repeat" cycle.

---

## Analysis Framework

Analyze the bug you just fixed from these 5 dimensions:

### 1. Root Cause Category

Which category does this bug belong to?

| Category | Characteristics | Example |
|----------|-----------------|---------|
| **A. Missing Spec** | No documentation on how to do it | New feature without checklist |
| **B. Cross-Layer Contract** | Interface between layers unclear | API returns different format than expected |
| **C. Change Propagation Failure** | Changed one place, missed others | Changed function signature, missed call sites |
| **D. Test Coverage Gap** | Unit test passes, integration fails | Works alone, breaks when combined |
| **E. Implicit Assumption** | Code relies on undocumented assumption | Timestamp seconds vs milliseconds |

### 2. Why Fixes Failed (if applicable)

If you tried multiple fixes before succeeding, analyze each failure:

- **Surface Fix**: Fixed symptom, not root cause
- **Incomplete Scope**: Found root cause, didn't cover all cases
- **Tool Limitation**: grep missed it, type check wasn't strict
- **Mental Model**: Kept looking in same layer, didn't think cross-layer

### 3. Prevention Mechanisms

What mechanisms would prevent this from happening again?

| Type | Description | Example |
|------|-------------|---------|
| **Documentation** | Write it down so people know | Update thinking guide |
| **Architecture** | Make the error impossible structurally | Type-safe wrappers |
| **Compile-time** | Strict type checking, no escape hatches | Signature change causes compile error |
| **Runtime** | Monitoring, alerts, scans | Detect orphan entities |
| **Test Coverage** | E2E tests, integration tests | Verify full flow |
| **Code Review** | Checklist, PR template | "Did you check X?" |

### 4. Systematic Expansion

What broader problems does this bug reveal?

- **Similar Issues**: Where else might this problem exist?
- **Design Flaw**: Is there a fundamental architecture issue?
- **Process Flaw**: Is there a development process improvement?
- **Knowledge Gap**: Is the team missing some understanding?

### 5. Knowledge Capture

Solidify insights into the system:

- [ ] Update `.trellis/spec/guides/` thinking guides
- [ ] Update relevant `.trellis/spec/` docs
- [ ] Create issue record (if applicable)
- [ ] Create feature ticket for root fix
- [ ] Update check guidelines if needed

---

## Output Format

Please output analysis in this format:

```markdown
## Bug Analysis: [Short Description]

### 1. Root Cause Category
- **Category**: [A/B/C/D/E] - [Category Name]
- **Specific Cause**: [Detailed description]

### 2. Why Fixes Failed (if applicable)
1. [First attempt]: [Why it failed]
2. [Second attempt]: [Why it failed]
...

### 3. Prevention Mechanisms
| Priority | Mechanism | Specific Action | Status |
|----------|-----------|-----------------|--------|
| P0 | ... | ... | TODO/DONE |

### 4. Systematic Expansion
- **Similar Issues**: [List places with similar problems]
- **Design Improvement**: [Architecture-level suggestions]
- **Process Improvement**: [Development process suggestions]

### 5. Knowledge Capture
- [ ] [Documents to update / tickets to create]
```

---

## Core Philosophy

> **The value of debugging is not in fixing the bug, but in making this class of bugs never happen again.**

Three levels of insight:
1. **Tactical**: How to fix THIS bug
2. **Strategic**: How to prevent THIS CLASS of bugs
3. **Philosophical**: How to expand thinking patterns

30 minutes of analysis saves 30 hours of future debugging.

## Thinking Framework: Bayesian Reasoning

When multiple root causes are plausible and evidence is incomplete, update your beliefs proportionally to new evidence rather than clinging to initial assumptions.

### Step 1: Establish Priors

Before investigating, state what you believe and why:

| Hypothesis | Prior | Reasoning |
|------------|-------|-----------|
| H1: [cause A] | 40% | Most common for this pattern |
| H2: [cause B] | 30% | Plausible given environment |
| H3: [other] | 30% | Catch-all |

Priors must sum to 100%. If you can't assign probabilities, investigate first.

### Step 2: Observe Evidence

Document what you found — be specific about reliability:

- What exactly did you observe?
- How reliable? (test output > log message > user report > hunch)
- Could multiple hypotheses explain this?

### Step 3: Update Beliefs

For each hypothesis, ask: **How likely is this evidence if this hypothesis were true?**

Direction of update matters more than calculation:
- Evidence strongly predicted by H1 → H1 probability increases
- Evidence contradicts H2 → H2 probability decreases
- Evidence equally likely under all → no update

### Step 4: Seek Discriminating Evidence

Don't gather more of the same. Find evidence that **differs strongly** between top hypotheses.

> If H1 and H3 are close: "What would I see if H1 is true but not if H3 is true?" Then check for that.

### Step 5: State Confidence

| Confidence | Action |
|------------|--------|
| 90%+ | Proceed with fix, monitor |
| 70-90% | Proceed, add fallback check |
| 50-70% | Test hypothesis before committing |
| <50% | Need more evidence, don't guess |

Never express binary certainty when evidence is incomplete. Use "most likely", "plausible but unlikely", "worth investigating".

### Common Fallacies

| Fallacy | Example | Correction |
|---------|---------|------------|
| **Base rate neglect** | "Test failed → code is broken" | How often do tests fail for other reasons? |
| **Confirmation bias** | "Must be a race condition, let me find race evidence" | Actively seek evidence AGAINST your top hypothesis |
| **Anchoring** | "Last time it was caching, probably caching again" | Establish priors from current context, not yesterday's bug |

---

## After Analysis: Immediate Actions

**IMPORTANT**: After completing the analysis above, you MUST immediately:

1. **Update spec/guides** - Don't just list TODOs, actually update the relevant files:
   - If it's a cross-platform issue → update `cross-platform-thinking-guide.md`
   - If it's a cross-layer issue → update `cross-layer-thinking-guide.md`
   - If it's a code reuse issue → update `code-reuse-thinking-guide.md`
   - If it's domain-specific → update `backend/*.md` or `frontend/*.md`

2. **Sync templates** - After updating `.trellis/spec/`, sync to `src/templates/markdown/spec/`

3. **Commit the spec updates** - This is the primary output, not just the analysis text

> **The analysis is worthless if it stays in chat. The value is in the updated specs.**
