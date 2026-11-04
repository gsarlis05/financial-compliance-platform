# Customer payment behaviour

**Customers & suppliers → Payment behaviour** shows how late each customer pays. The cash forecast
dates each open invoice at its due date plus the customer's days late.

- **Observed days late:** the average of (date fully paid − due date) over the customer's invoices
  that were fully paid in the last 12 months.
  - The average is weighted by invoice amount, so large invoices count for more.
  - Paying early counts as negative days.
  - The result is rounded to whole days.
- **Too few invoices:** at least 3 fully paid invoices are needed. With fewer, the forecast assumes
  0 days late, and the note says so.
- **When an invoice counts:** an invoice counts once it is fully allocated to payments or credit
  notes; the date is the allocation that completed it. Partly paid invoices are not counted yet.
- **Override:** an override (from 60 days early to 365 days late) replaces the observed value, for
  example for a customer who has agreed a payment plan. Clear it to go back to the observed
  value. Changes are in the audit trail.
