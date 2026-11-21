# Postmortem: INC-2047 Billing Invoice Generation Outage

**Severity:** SEV1
**Date of incident:** 3 September 2026
**Duration:** 2 hours 47 minutes (09:12 to 11:59 IST)
**Incident commander:** Riya Deshpande
**Status:** Action items in progress

## Summary

On 3 September 2026, the billing service failed to generate monthly invoices for 2,318 customers. Customers on annual plans were not affected. In addition, 41 customers were charged twice for their August usage before the issue was contained. All duplicate charges were refunded within 48 hours, and no customer data was lost.

## Impact

- 2,318 monthly-plan customers did not receive their invoice on time.
- 41 customers were double-charged, for a total of USD 18,940, which was fully refunded.
- The customer support team received 186 tickets related to the incident.
- The billing dashboard showed incorrect revenue figures for about 6 hours.

## Root Cause

The billing service runs a nightly job that generates invoices in batches of 500 customers. A schema migration deployed on 2 September added a new `tax_region` column to the invoices table, and the migration was deployed together with the application code instead of separately, contrary to our deployment guidelines.

The migration ran a table rewrite that held a lock for 14 minutes. During that window, the invoice job hit its 10-minute timeout and the retry logic re-submitted batches that had already been partially processed. Because the payment step was not idempotent, customers in partially processed batches were charged again on retry.

The root cause was therefore a combination of a non-backward-compatible migration deployed alongside code, and a payment step without an idempotency key.

## Timeline (IST)

- 02:00: Nightly invoice job starts; migration lock blocks writes.
- 02:10: First batch times out and retries.
- 09:12: Support escalates reports of duplicate charges; SEV1 declared.
- 09:40: Invoice job paused; payment processing halted.
- 10:25: Root cause identified as the migration lock combined with non-idempotent retries.
- 11:30: Fix deployed: idempotency keys added to the payment call.
- 11:59: Invoice job re-run successfully; incident resolved.

## What Went Well

- The finance team identified all affected customers within 30 minutes using the payment provider's export.
- Refunds were automated with a one-off script, avoiding manual errors.

## What Went Wrong

- The migration was not reviewed by the Data Infrastructure team.
- Alerting on duplicate payment attempts did not exist, so the issue was found by customers rather than by monitoring.
- The on-call engineer was not paged for the job timeouts because they were logged at WARNING level instead of triggering an alert.

## Action Items

1. Add idempotency keys to every call to the payment provider. Owner: Revenue Engineering. Status: done.
2. Add a CI check that blocks pull requests containing both a schema migration and application code. Owner: Platform. Due: 30 September 2026.
3. Create an alert for more than 5 payment attempts for the same customer within 24 hours. Owner: Revenue Engineering. Due: 20 September 2026.
4. Require Data Infrastructure review for any migration on tables larger than 10 million rows. Owner: Data Infrastructure. Due: 15 October 2026.
5. Page on-call when the invoice job fails or times out more than twice in a run. Owner: Revenue Engineering. Due: 20 September 2026.

## Lessons Learned

Retries are only safe when the operation being retried is idempotent. Every external side effect, especially anything that moves money, must carry an idempotency key.
