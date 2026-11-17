# Creole Studios Zoho Projects conventions

Observed from the live portal (read-only) and the Zoho Task Evaluation guide.

## Portal
- Portal name `creolestudiosdotcom1` (Creole Studios), timezone Asia/Kolkata. Resolve the numeric portal id with `get_portals`; never hardcode.
- Example project: *Research & Training 2025*, task list *Task List 2026*. Resolve ids by name with `get_projects_list` / `get_all_project_task_lists`.

## Hierarchy (depth 0 → 2)
| Depth | Example | Notes |
|-------|---------|-------|
| 0 weekly parent | `W47 - Sample tasks added by CKP by individual users - 20 hours (Asha 14, Ravi 6)` | one per week |
| 1 person bucket | `Asha: 14 hours` | one per person per week, status Backlog |
| 2 task | `Zoho Automatic Task Creation Research & Training [8.0 hrs]` | the unit that is evaluated |

Create tasks under the person's bucket for the current week (`parental_info.parent_task_id`). If the bucket does not exist, tell the user and ask before creating it.

## Title
`<Imperative, specific title> [X.X hrs]`
- Start with a verb (Implement, Fix, Upgrade, Review, Migrate…), name the system/module, ≤ 200 characters.
- Append the planned hours as `[X.X hrs]` (one decimal). Hours must equal the task's planned duration.
- **Empty title fallback:** derive from the description — first strong verb + object + system, e.g. description "Upgrade PHP 8.3 to 8.5 and WordPress 7.0 to 7.1 on Site A" → `Upgrade PHP and WordPress on Site A [4.0 hrs]`. Never use "Task", "Update", "Work", "Misc".
- Meetings: `Meeting – <purpose> [X.X hrs]` under a dedicated meeting task.

## Description (40–60 words)
Scope, requirements, files/modules/APIs/schemas involved, and what "done" looks like. > 6 words minimum, never empty.

## Time
- Duration/work are `HH:MM` hours. Planned vs logged is scored; grace buffer is +5 minutes.
- Billing type: `billable`, `non_billable` or `none` — ask if unclear.

## Statuses
Backlog → In Progress → **In QA Review** (final state for developers) → Completed (human only).
Resolve each status id at runtime via the field-options lookup for `tasks` / `status` filtered by project; ids differ per portal and project, so never hardcode them.
Status is sent as `status: {"id": "<id>"}`; names are rejected by the API.

## "Last create" defaults
When project/list/parent are unspecified, read the most recently created task (`sort_by=DESC(created_time)`), reuse its project, task list and parent bucket, and confirm with the user.
