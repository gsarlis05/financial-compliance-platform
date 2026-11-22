# Scenarios

A scenario answers "what if?": it takes an **approved assumption set** (Cash & planning →
Assumptions) and changes some of its assumptions, so you can compare the result with the plan.
Every figure a scenario produces is **hypothetical**. A scenario never changes the assumptions it is
based on, a budget, a forecast or the books.

Scenario results, comparisons and screens follow in the next releases (M7-2 and M7-7). This page
describes how scenarios are set up.

## Starting a scenario
Choose an approved assumption set of the entity as the **base** and give the scenario a name. It
starts as your **draft**: only you can see it. Add changes (overrides) one by one. They apply in the
order listed, which you can change.

## The eight kinds of change
| Change | Example | What you enter |
|---|---|---|
| Percent change | Revenue −15% from March | revenue or costs, which lines (none = all), the %, first and last month |
| Amount change | Payroll +€8,000 a month | revenue or cost line, the amount a month (negative to reduce), first and last month |
| Timing shift | Customers pay 60 days later | days added to (or taken from) DSO, DIO or DPO; or a revenue or cost line moved by whole months |
| New loan | €200,000 over 5 years at 6% | a code, the amount, the month it is drawn, months, the yearly rate, annuity, equal principal or bullet, interest-only months |
| New hire | 2 people from March at €2,100 | role, department, how many, gross monthly salary, employer cost % **and where it comes from**, first and last month |
| Investment | €150,000 of equipment in May | amount, month, useful life in months, paid in cash or with a loan (its terms) |
| One-off payment | Unexpected tax payment of €40,000 | amount, month, and whether it is an expense (which cost line) or settles a liability (trade, other or tax payables) |
| Rate change | Interest +2 percentage points from June | all debt, the credit facility, other debt, or named loans; the points; from which month |

Every month must lie inside the base's horizon. If something is wrong, the message names the field
and says what to enter, for example "start_month: 03/2028 is outside the base's horizon (01/2027
to 12/2027)."

**Employer costs of a new hire:** the platform holds no social-insurance or other contribution
rate, because none has been verified by a professional. Enter the employer cost % yourself and say
where it comes from (for example your payroll adviser). The source is kept with the scenario.

## Sharing, copying and archiving
- **Share** makes the scenario visible to everyone who can read plans for the entity. A shared
  scenario never changes; to change it, **copy** it (the copy is your new draft).
- When a newer version of the base is approved, the scenario keeps its base and says "a newer
  version is approved". Copy it onto the new version to **rebase** it: every change is checked
  again, and the first one that no longer fits is named.
- **Archive** a scenario you no longer need. Nothing is deleted. You can archive your own
  scenarios; archiving someone else's needs the right to publish plans.

## Who can do what
| | Read plans | Run plans | Publish plans |
|---|---|---|---|
| See shared and archived scenarios | ✔ | ✔ | ✔ |
| Create, change, share and copy your scenarios | | ✔ | ✔ |
| Archive someone else's scenario | | | ✔ |

Every change is recorded in the audit trail.
