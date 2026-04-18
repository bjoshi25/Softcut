# Engineering Truth Review Prompt

Challenge the engineering shape of the project. Be direct, evidence-based, and
useful.

## Instructions

Inspect architecture, contracts, maintainability, and hidden rework risk.
Prioritize concrete risks over preference.

## Questions To Challenge

- Are the boundaries clear enough to change safely?
- Are contracts explicit where errors would be expensive?
- Is the implementation simpler than the problem requires, or more complex?
- Are side effects isolated and observable?
- Are invalid states handled clearly?
- Are dependencies justified and maintained?
- Is there hidden coupling that will make the next change expensive?
- Are tests aimed at real risk or only at easy cases?
- Are docs honest about current behavior and limitations?

## Output

Start with findings ordered by severity. End with:

- recommended engineering actions
- decisions that should become ADRs
- risks that can be accepted for now
