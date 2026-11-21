# Engineering Onboarding Guide

Welcome to the Northwind Labs engineering team. This guide covers your first two weeks, our development workflow, how code reaches production, and how on-call works. Your onboarding buddy will walk through it with you on day one.

## Your First Two Weeks

By the end of week one you should have a working local environment, have merged at least one small pull request, and have shadowed one deploy. By the end of week two you should have completed the security training, joined the on-call shadow rotation and paired with an engineer from another team for at least half a day.

New engineers do not join the primary on-call rotation until they have been at Northwind Labs for at least 8 weeks and have completed two shadow shifts.

## Tech Stack

Orbit Analytics is built as a set of services. The ingestion pipeline is written in Go and receives roughly 4 billion events per day. The query service is written in Rust and runs on top of ClickHouse. The web application uses TypeScript with Next.js, and internal tooling is mostly Python.

Service | Language | Owner team | Datastore
Event Ingest | Go | Platform | Kafka, S3
Query Engine | Rust | Data Infrastructure | ClickHouse
Web App | TypeScript / Next.js | Product Engineering | PostgreSQL
Billing | Python | Revenue Engineering | PostgreSQL
Feature Flags | Go | Platform | Redis

## Local Development Setup

All services run locally through a single command, `make dev`, which starts Docker Compose with seeded test data. You need Docker Desktop, Go 1.24, Rust (stable), Node.js 22 and Python 3.12. The setup script `./scripts/bootstrap.sh` installs the remaining tools and checks your versions.

Never use production credentials locally. Local development uses the synthetic dataset "Acme Demo", which contains 30 days of generated events for 5 fictional customers.

## Code Review

Every change to a production service needs at least one approving review from a member of the owning team. Changes to the billing service or to authentication code need two approvals, one of which must be from a senior engineer (L5 or above).

Pull requests should be small: aim for fewer than 400 changed lines. Reviewers are expected to respond within one working day. If a review is blocking you for longer, it is fine to ask in the team channel.

We use conventional commit messages such as `feat:`, `fix:` and `chore:`. The PR description must explain why the change is needed, how it was tested, and any rollout risk.

## Deployment Process

Northwind Labs practices continuous delivery. Merging to the main branch automatically deploys to the staging environment. Production deploys are triggered from the Deploy dashboard and roll out progressively: 5% of traffic for 15 minutes, then 25% for 15 minutes, then 100%.

The deploy pipeline automatically rolls back if the error rate rises more than 2 percentage points above the baseline or if p99 latency increases by more than 30% during any rollout stage.

Production deploys are not allowed on Fridays after 15:00 local time, on weekends, or during Recharge Week, unless the change is an incident fix approved by the incident commander. Database migrations must be backward compatible and are deployed separately from the application code that depends on them.

## On-Call

Each service team runs a weekly on-call rotation that changes over on Monday at 10:00 IST. The primary on-call engineer must acknowledge pages within 5 minutes and be able to start working on an incident within 15 minutes. A secondary on-call engineer is paged automatically if the primary does not acknowledge within 10 minutes.

On-call engineers receive a stipend of INR 8,000 per week, plus one day off for any week in which they were paged outside working hours more than three times.

Incidents are classified by severity. SEV1 means a full outage or data loss affecting customers; SEV2 means a major feature is degraded for many customers; SEV3 means a minor issue with a workaround. SEV1 and SEV2 incidents require a written postmortem within 5 working days. Postmortems are blameless and focus on systems, not individuals.

## Getting Help

Ask questions in #eng-help. For access requests use the Access Portal; production access is granted only after 4 weeks and requires manager approval. The engineering wiki is the source of truth for architecture decisions, which are recorded as ADRs (Architecture Decision Records).
