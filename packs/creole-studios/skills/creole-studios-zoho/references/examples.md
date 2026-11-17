# Before / after examples

## Titles
| Bad | Good |
|-----|------|
| `Update` | `Upgrade PHP and WordPress on Site A [4.0 hrs]` |
| `Dribble` | `Create Dribbble UI screens for landing page concept [1.0 hrs]` |
| *(empty, description: "Research Zoho API to auto-create weekly tasks")* | `Research Zoho API for automatic weekly task creation [8.0 hrs]` |
| `Meeting` | `Meeting – Sprint planning with client [1.0 hrs]` |

## Descriptions (40–60 words)
**Bad (3.5):** `Do php upgrade and testing.`

**Good (9+):**
> Upgrade the Site A and Site B sites from PHP 8.3.x to 8.5.12 after the Ubuntu OS upgrade, and move WordPress from 7.0.4 to 7.1.4. Review plugin and theme compatibility, take a backup first, and run smoke tests on both sites. Done when both sites load, forms submit and no PHP deprecation errors appear in logs.

## Progress comments (25–60 words, with test evidence)
**Bad (4.0):** `Done`
**Bad (5.2):** `1. Setup DB - Done, 2. Update API - Done, 3. Testing - Done`
**Bad (5.0, ≥3h task):** `UI done. API integration and tests pending for tomorrow.`

**Good (9.8):**
> Added `20261030_zoho_rls.sql` with role policies for analyst/admin and helper functions `current_tenant()` and `is_admin()`. Applied it on staging, fixed a policy recursion error, and confirmed 8 passing pgTAP cases including cross-tenant read denial.

**Good with a blocker (not capped):**
> Completed the dashboard layout and tested it on 3 viewports. API integration is blocked: staging credentials for the payments service have not been provided (requested from the client on Slack today). Will resume as soon as access is granted.

**Overrun roadblock comment (write immediately, not at close):**
> Running ~45 minutes over the 2h estimate: the migration fails on production-sized data because of a missing index on `orders.tenant_id`. Added the index in `0042_add_tenant_idx.sql`; re-running the migration now, expecting 20 more minutes.

## QA Review hand-off comment
> Self-tested on staging: ran 14 unit tests (all passing), manually checked empty-state and 500-error paths. Changed `invoice_service.py` and `routes/invoices.py`. Ready for QA Review; known limitation: PDF export for >500 rows is not covered.

## Meetings
Prefer a dedicated task `Meeting – <purpose> [X.X hrs]`. If time is logged in a technical task, add to the description: "Includes 1h client call on API scope" and comment what was decided ("Agreed to move pagination to cursor-based; client approves v2 payload").

## Full create → update flow (dry-run first)
1. User: "log my Site A upgrade, 4 hours, billable".
2. Agent reads last created task → project *Research & Training 2025*, list *Task List 2026*, parent `<Name>: N hours` → asks to confirm.
3. Agent drafts title/description, runs `lint_task.py --draft`, shows the payload.
4. After "yes": create task (Backlog/In Progress). On finish: comment as above, log hours, status → **In QA Review**.
