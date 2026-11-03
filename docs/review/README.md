# Review trackers

Four files that carry what matters between review runs. Claude Code writes
them during `/review`; you read them and decide. Keep all four in Git.

| File | Answers | Written when |
|---|---|---|
| `STATE.md` | Which files were reviewed, and at which commit | End of every stage |
| `FINDINGS.md` | What's open, what's settled, and why | During the audit, and when you decide |
| `NAMING.md` | Which word wins when two fit | When a term is settled |
| `REVIEW_LOG.md` | What each run covered and whether the checks passed | Start and end of every run |

`STATE.md` is the one that makes repeat runs cheap: it lets `/review new`
look only at files that changed since they were last read. The **Settled**
section of `FINDINGS.md` is what stops a later run from raising the same
thing twice.

Run `/review all` once to establish a baseline, then `/review new` at the
end of each milestone and before each release.
