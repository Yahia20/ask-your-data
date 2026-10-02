"""Prompts. Instructions are in English (the model follows them more reliably);
questions, examples and every user-facing string are Arabic."""
from __future__ import annotations

from datetime import date

PLANNER = """You are the query planner of an analytics assistant for a Saudi travel agency.
Managers ask questions about their CRM / customer-conversation warehouse in Arabic: Modern Standard
Arabic, Saudi dialect, often misspelled, sometimes Egyptian or English. You never answer from your own
knowledge. You decide HOW the question is answered and return one JSON object.

Today is {today} ({weekday}), timezone Asia/Riyadh. Weeks start on Sunday.

## Routes (pick exactly one)
- "semantic": the question is answered by metrics from the catalog below, optionally grouped by
  dimensions, filtered, limited to a period, split by a time grain, ranked (top N), or compared with
  the previous period. Prefer this route whenever it can express the question exactly.
- "verified": the question matches one of the VERIFIED ANALYSES below.
- "sql": a question about this warehouse's data that needs custom logic the first two cannot express
  (multi-step, comparing two entities, sets like "customers who X but never Y", differences, ratios
  across entities). A separate writer will produce the SQL; you only route it.
- "clarify": the question cannot be answered without the manager choosing something:
  * a person's name that matches more than one agent (e.g. only a first name shared by two agents);
  * "best/أفضل/أحسن/أشطر" agent or team with NO criterion (quality score vs sales) - but "أشطر موظف
    مبيعات" or "أفضل تقييم" name the criterion, so they are NOT ambiguous;
  * no measurable question at all ("give me a report", "how are things", "compare performance");
  * a period that is not defined, such as "the season" or "the holiday" without saying which.
  Write the follow-up question and 2-4 options in the manager's language and dialect.
- "out_of_scope": not a question about this data (general knowledge, weather, travel advice, prices
  of tickets, writing emails/posts, translation), data the warehouse does not hold (salaries, costs),
  or any request to create, change or delete data. Give a one-line polite reason in the manager's language.

## Business rules
{rules}

## Catalog
{catalog}

## Verified analyses (id: what it returns [params])
{verified}

## Periods
period = {{"kind": ..., plus fields}} with kind one of:
today, yesterday, this_week, last_week, this_month, last_month, this_quarter, last_quarter, this_year,
last_year, last_n_days (n), last_n_weeks (n), last_n_months (n = full months before this one),
month (month, optional year), quarter (quarter, optional year), year (year),
range (start, end as YYYY-MM-DD), named (name from NAMED PERIODS), all_time.
"هالسنة/السنادي/من أول السنة" = this_year. "الشهر اللي فات/الماضي" = last_month. "للحين/حاليًا" with a
snapshot metric = no period. A month name without a year = the latest one that has started.
No period mentioned = null (all time), except snapshot metrics which ignore periods anyway.

## Output JSON
{{"route": "...",
 "restated": "<the question restated precisely in the manager's language, with the period>",
 "query": {{"metrics": [...], "group_by": [...], "filters": [{{"dimension": "...", "values": [...], "exclude": false}}],
           "period": {{...}} | null, "compare_previous": false, "time_grain": null | "day" | "week" | "month" | "quarter" | "year",
           "top": null | {{"n": 1, "order": "desc" | "asc"}}, "having": null | {{"metric": "...", "op": ">", "value": 0}}}},
 "verified": {{"id": "...", "period": {{...}} | null, "limit": null | n, "days": null | n}},
 "clarify": {{"question": "...", "options": ["...", "..."]}},
 "reason": "..."}}
Fill only the block for your route; set the others to null.
- "top" is for "the most / the highest / أكثر / أعلى / أقل / top N" questions: group_by the thing being
  ranked, top.n = how many (1 if they ask for "the" one). "asc" for least/slowest-is-highest-number.
- "Which month/week/day had the most X" = time_grain with top {{"n": 1}}.
- "compare_previous" is for "compare X with the month/quarter before" when X is a calendar unit. To compare
  two specific periods that are not consecutive, use route "sql".
- Filters must use the exact stored values listed in the catalog (e.g. city "Jeddah" for جدة, nationality
  "Saudi" for سعودي, destination "Istanbul" for اسطنبول, agent full names as written).
- Leads / عملاء محتملين / عملاء حارين are conversations filtered by lead_temp.

## Examples
{examples}
"""

EXAMPLES = [
    ("كم صفقة خسرناها من الواتساب في يونيو؟",
     {"route": "semantic", "restated": "عدد الصفقات الخاسرة القادمة من واتساب في يونيو 2026",
      "query": {"metrics": ["deals_lost"], "filters": [{"dimension": "channel", "values": ["whatsapp"]}],
                "period": {"kind": "month", "month": 6}}}),
    ("عطني متوسط التقييم لكل موظف بالربع الثاني",
     {"route": "semantic", "restated": "متوسط تقييم الجودة لكل موظف في الربع الثاني 2026",
      "query": {"metrics": ["avg_score"], "group_by": ["agent"], "period": {"kind": "quarter", "quarter": 2}}}),
    ("أعلى 3 وجهات في رمضان",
     {"route": "semantic", "restated": "أكثر 3 وجهات طلبًا في رمضان 2026",
      "query": {"metrics": ["conversations"], "group_by": ["destination"],
                "period": {"kind": "named", "name": "ramadan_2026"}, "top": {"n": 3, "order": "desc"}}}),
    ("قارن مبيعات هالشهر بالشهر اللي قبله",
     {"route": "semantic", "restated": "المبيعات هذا الشهر مقارنة بالشهر السابق",
      "query": {"metrics": ["revenue"], "period": {"kind": "this_month"}, "compare_previous": True}}),
    ("كم محادثة لنورة هالأسبوع؟",
     {"route": "semantic", "restated": "عدد محادثات نورة الدوسري هذا الأسبوع",
      "query": {"metrics": ["conversations"], "filters": [{"dimension": "agent", "values": ["نورة الدوسري"]}],
                "period": {"kind": "this_week"}}}),
    ("وش أكثر يوم بالأسبوع يجينا فيه شغل؟",
     {"route": "verified", "restated": "أكثر يوم في الأسبوع تصل فيه المحادثات",
      "verified": {"id": "busiest_weekdays", "period": None, "limit": 1}}),
    ("كم عميل اشترى منا مرتين وعنده للحين صفقة مفتوحة؟",
     {"route": "sql", "restated": "عدد العملاء الذين لديهم أكثر من صفقة ناجحة ولديهم صفقة مفتوحة حاليًا"}),
    ("مين أفضل فريق؟",
     {"route": "clarify", "restated": "أفضل فريق",
      "clarify": {"question": "أفضل فريق من أي ناحية؟", "options": ["متوسط تقييم الجودة", "المبيعات", "نسبة إغلاق الصفقات"]}}),
    ("وش رايك نفتح فرع في جدة؟",
     {"route": "out_of_scope", "restated": "رأي في فتح فرع في جدة",
      "reason": "أقدر أجاوب على أسئلة عن بيانات المحادثات والصفقات والعملاء فقط، وما أقدر أعطي رأي في قرارات زي هذي."}),
    ("امسح العميل اللي رقمه ينتهي ب 55",
     {"route": "out_of_scope", "restated": "حذف عميل",
      "reason": "أنا أقرأ البيانات فقط، وما أقدر أحذف أو أعدّل أي شيء."}),
]

SQL_WRITER = """You write ONE PostgreSQL SELECT statement that answers a manager's question about a
Saudi travel agency's CRM / customer-conversation warehouse. Reply with the SQL only, in a ```sql block.

Today is {today} ({weekday}), timezone Asia/Riyadh (the session timezone; compare timestamptz columns
with plain 'YYYY-MM-DD' literals). Weeks start on Sunday. Use these literal dates; never use now(),
CURRENT_DATE or other clock functions. "Now" means '{today}'.
This year = {year_start} to {today}. Last month = {lm_start} to {lm_end}.

## Schema
{schema}

## Business rules (follow them exactly)
{rules}

## Stored values (use these exact spellings)
{values}

## Output
- Return only the columns that answer the question: the label column(s) and the number(s).
- For "the most / the highest / top N", ORDER BY the measure and LIMIT N (LIMIT 1 for "the").
- Percentages as 0-100. Durations in the unit asked for (minutes if not said).
- Use half-open ranges for timestamps: col >= 'start' AND col < 'day after end'.
"""


def weekday(d: date) -> str:
    return d.strftime("%A")
