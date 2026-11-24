# Scenarios

A scenario answers "what if?": it takes an **approved assumption set** (Cash & planning →
Assumptions) and changes some of its assumptions, so you can compare the result with the plan.
Every figure a scenario produces is **hypothetical**. A scenario never changes the assumptions it is
based on, a budget, a forecast or the books.

Screens: **Cash & planning → Scenarios**, **Sensitivity** and **Working capital**, and a section on
each goal (**Goals**, select a goal). Scenario figures are drawn as dotted lines and named
"hypothetical" in words, so they never depend on colour alone; every chart has a table with the
same figures.

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
| One-off payment | Unexpected tax payment of €40,000 | amount, month, and whether it is an expense (which cost line) or settles part of a liability (other payables, or VAT and other taxes payable) |
| Rate change | Interest +2 percentage points from June | all debt, the credit facility, other debt, or named loans; the points; from which month |

Every month must lie inside the base's horizon. If something is wrong, the message names the field
and says what to enter, for example "start_month: 03/2028 is outside the base's horizon (01/2027
to 12/2027)."

**Employer costs of a new hire:** the platform holds no social-insurance or other contribution
rate, because none has been verified by a professional. Enter the employer cost % yourself and say
where it comes from (for example your payroll adviser). The source is kept with the scenario.

## Results: the comparison with the base
**Compare** runs the scenario now on the current books and shows it next to its base, by month,
quarter or year: the income statement, balance sheet and cash flow statement, with the difference
on every line. Every scenario figure is labelled **hypothetical**; the opening balance sheet is the
actual one.

- **What changed and why:** for each change, its effect on revenue, EBITDA, net income and net cash
  flow over the horizon, and on cash and debt at its end. The effects add up exactly to the total.
  Every changed figure also lists the changes that moved it.
- **Liquidity:** lowest cash and its month, the first month cash would be negative, months below
  the minimum cash, the peak use of the credit facility and the debt at the end, for the base and
  the scenario.
- **Checks:** the scenario's statements pass the same eight checks as any projection (the balance
  sheet balances, cash ties, and so on). If one fails, it says where.
- The projection engine is still **pending professional review**, and so are its scenarios.

Changes apply in their order, each to the result of the ones before. A one-off payment can settle
at most the liability's balance at the cut-over. Moving a line by whole months drops what moves past
the end of the window, and the comparison says how much.

**Save** records the scenario's run, so it can be reproduced later; a saved scenario run is never
published as an official forecast.

**Export to Excel** downloads the comparison in the period you are viewing and in your language:
one sheet per statement with the base, the scenario and the difference for each period, a
"Nature" row above the figures (actual for the opening balance sheet, hypothetical otherwise), and
a sheet with the change made by each override. Every sheet says that the figures are hypothetical,
not actual results and not an approved forecast. Exporting needs the right to export reports and
is recorded in the audit trail.

Once the scenario is **shared**, the comparison also shows the KPI library on the scenario's
first year next to the base's.

## Which assumptions matter most: sensitivity and tornado
Start from an approved assumption set, or from a **shared** scenario.

- **One variable:** choose one assumption (for example revenue, rent, customer days) and a range
  (for example −20% to +20%, or 0 to 60 more days for customer, stock or supplier days), in up to 11
  steps. You get the result at each step and its change from the base.
- **Tornado:** every assumption is moved down and up by the same % (10% unless you choose), one at
  a time. The assumptions are ranked by how much the result moves between the two; equal ones are
  listed by name.
- **Results you can choose:** the lowest month-end cash, cash at the end, the number of months
  before cash first goes below zero, or EBITDA or net income for a year.

Results are hypothetical and are not saved. Asking the same question again on the same books gives
the cached answer at once. To protect the service there is a limit on how many analyses one person
and one workspace can run each minute, and on how long one analysis may take; the message says what
to do if you reach it.

## Working capital
For an approved assumption set, or a shared scenario, the working-capital view shows month by
month the customer receivables, stock and supplier payables the projection holds; net working
capital (receivables + stock − payables), its change, and what that change does to cash; and the
days that drive them (customer days DSO, stock days DIO, supplier days DPO) with the cash
conversion cycle (DSO + DIO − DPO). Next to them are the days actually seen over the 12 months to
the cut-over.

**What are N days worth?** Choose customer, stock or supplier days and a number of days (for
example customers paying 10 days sooner: −10 customer days). The projection is run again with
those days changed for every month, and you see the cash released (or tied up) by month, at the
end, at its lowest point, and the change in working capital. Each balance is rounded to cents on
its own, so the answer can differ by a cent from a quick hand calculation.

## Goals against scenarios
Each goal can be tested against up to three shared scenarios, side by side with its base: the
likely outcome, the gap and the status under each, labelled hypothetical. Nothing is saved and the
goal never changes (see the goals guide).

## Turning a scenario into a plan
**Create an assumption-set draft** copies the base with the changes written into its values and
loans. The draft then goes through the normal review and approval. Two kinds of change cannot be
held by an assumption set, and are refused with their names: a payment that settles a liability,
and an investment in a month that already has capital expenditure with another useful life.

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
| Compare, save a run, create a draft set from a scenario | | ✔ | ✔ |
| See saved scenario runs | ✔ | ✔ | ✔ |
| Run sensitivity and tornado analyses | | ✔ | ✔ |
| See the working-capital view and what N days are worth | | ✔ | ✔ |
| Test goals against shared scenarios | | ✔ | ✔ |
| Archive someone else's scenario | | | ✔ |

Every change is recorded in the audit trail.
