"""Build the demo warehouse: data/demo.duckdb.

Everything here is invented. Names, phones and amounts are random; only the
shape (tables, columns, enum values, business rules) follows the production
schema. The seed is fixed, so every run produces the same file and the test
set's expected answers never drift.

    python data/generate.py
"""
from __future__ import annotations

import random
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import duckdb
import pandas as pd

HERE = Path(__file__).parent
DB_PATH = HERE / "demo.duckdb"
RIYADH = timezone(timedelta(hours=3))
START, END = date(2026, 1, 1), date(2026, 10, 1)   # conversations; "today" is 2026-10-02
TODAY = datetime(2026, 10, 2, 9, 0, tzinfo=RIYADH)

rng = random.Random(2026)


def uid() -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def at(day: date, hour: float) -> datetime:
    return datetime.combine(day, time(0), RIYADH) + timedelta(hours=hour)


# --------------------------------------------------------------------------- agents
# skill drives quality scores and win rates; speed drives first-response time;
# discipline drives whether follow-up promises are kept.
AGENTS = [
    # name,                team,      skill, speed_min, discipline, hired,        active
    ("أحمد الغامدي",       "sales",   82, 4,  0.85, date(2023, 3, 1), True),
    ("محمد العتيبي",       "sales",   74, 9,  0.70, date(2024, 1, 15), True),
    ("محمد الشهري",        "sales",   66, 15, 0.55, date(2025, 6, 1), True),
    ("سارة القحطاني",      "sales",   86, 6,  0.90, date(2022, 9, 10), True),
    ("نورة الدوسري",       "support", 78, 3,  0.80, date(2024, 4, 20), True),
    ("فهد الحربي",         "sales",   70, 12, 0.60, date(2025, 2, 1), True),
    ("ريم الزهراني",       "sales",   80, 7,  0.75, date(2023, 11, 5), True),
    ("عبدالرحمن المطيري",  "support", 72, 5,  0.65, date(2024, 8, 1), True),
    ("هبة عبدالعزيز",      "sales",   76, 8,  0.80, date(2025, 1, 10), True),
    ("خالد السبيعي",       "sales",   60, 20, 0.45, date(2024, 2, 1), False),  # left in June
]
KHALED_LEFT = date(2026, 6, 15)

agents = []
for i, (name, team, skill, speed, disc, hired, active) in enumerate(AGENTS):
    agents.append(dict(agent_id=uid(), bitrix_user_id=str(100 + i), full_name=name, team=team,
                       is_bot=False, is_active=active, hired_at=hired,
                       _skill=skill, _speed=speed, _disc=disc))
bot = dict(agent_id=uid(), bitrix_user_id="1", full_name="بوت الاستقبال", team="bot", is_bot=True,
           is_active=True, hired_at=date(2025, 9, 1), _skill=0, _speed=0.1, _disc=0)
humans = agents
sales_agents = [a for a in agents if a["team"] == "sales"]

# --------------------------------------------------------------------------- destinations
DESTS = [  # canonical, country, region, kind, aliases, weight
    ("Istanbul", "TR", "Turkey", "city", ["إسطنبول", "اسطنبول", "استنبول"], 14),
    ("Trabzon", "TR", "Turkey", "city", ["طرابزون", "ترابزون"], 7),
    ("Bursa", "TR", "Turkey", "city", ["بورصة", "بورصه"], 3),
    ("Antalya", "TR", "Turkey", "city", ["أنطاليا", "انطاليا"], 3),
    ("Dubai", "AE", "Gulf", "city", ["دبي", "دبى"], 9),
    ("Cairo", "EG", "Egypt", "city", ["القاهرة", "القاهره"], 6),
    ("Sharm El Sheikh", "EG", "Egypt", "city", ["شرم الشيخ", "شرم"], 4),
    ("Baku", "AZ", "Caucasus", "city", ["باكو"], 6),
    ("Tbilisi", "GE", "Caucasus", "city", ["تبليسي", "تبليس"], 4),
    ("Batumi", "GE", "Caucasus", "city", ["باتومي"], 3),
    ("Bosnia", "BA", "Europe", "country", ["البوسنة", "البوسنه", "سراييفو"], 4),
    ("Bali", "ID", "Asia", "city", ["بالي"], 4),
    ("Maldives", "MV", "Asia", "country", ["المالديف", "جزر المالديف"], 4),
    ("Kuala Lumpur", "MY", "Asia", "city", ["كوالالمبور", "كوالا لمبور", "ماليزيا"], 5),
    ("London", "GB", "Europe", "city", ["لندن"], 4),
    ("Paris", "FR", "Europe", "city", ["باريس"], 3),
    ("Switzerland", "CH", "Europe", "country", ["سويسرا"], 3),
    ("Makkah", "SA", "Saudi", "city", ["مكة", "مكه", "مكة المكرمة"], 8),
    ("Madinah", "SA", "Saudi", "city", ["المدينة", "المدينة المنورة"], 4),
    ("Riyadh", "SA", "Saudi", "city", ["الرياض"], 0),   # origins only
    ("Jeddah", "SA", "Saudi", "city", ["جدة", "جده"], 0),
]
destinations, aliases = [], []
for i, (name, cc, region, kind, al, _w) in enumerate(DESTS, start=1):
    destinations.append(dict(destination_id=i, canonical_name=name, country_code=cc, region=region, kind=kind))
    for a in al:
        aliases.append(dict(alias_id=len(aliases) + 1, destination_id=i, alias=a, lang="ar"))
dest_id = {d["canonical_name"]: d["destination_id"] for d in destinations}
dest_ar = {d[0]: d[4][0] for d in DESTS}
TRIP_DESTS = [(d[0], d[5]) for d in DESTS if d[5] > 0]

# --------------------------------------------------------------------------- customers
NATIONALITIES = [  # nationality, country, phone prefix, cities, weight
    ("Saudi", "SA", "+9665", ["Riyadh"] * 5 + ["Jeddah"] * 4 + ["Dammam"] * 2 + ["Makkah", "Madinah", "Abha", "Khobar", "Tabuk"], 70),
    ("Egyptian", "EG", "+2010", ["Cairo"] * 4 + ["Alexandria", "Giza"], 17),
    ("Kuwaiti", "KW", "+9655", ["Kuwait City"], 5),
    ("Emirati", "AE", "+9715", ["Dubai", "Abu Dhabi"], 3),
    ("Jordanian", "JO", "+9627", ["Amman"], 3),
    ("Yemeni", "SA", "+9665", ["Riyadh", "Jeddah"], 2),   # lives in KSA
]
FIRST = ["عبدالله", "فيصل", "منيرة", "سلطان", "هيا", "تركي", "لمى", "ناصر", "جواهر", "بندر", "أمل", "ماجد",
         "أحمد", "محمد", "مريم", "يوسف", "نوف", "سعود", "دانة", "عمر", "خالد", "رنا", "مصطفى", "شيماء"]
LAST = ["السبيعي", "العنزي", "الشمري", "البقمي", "الرشيدي", "اليامي", "العمري", "الجهني", "المالكي",
        "الحارثي", "عبدالحميد", "السيد", "حسن", "الكندري", "النعيمي", "الخطيب"]

customers, phones = [], set()
for _ in range(5200):
    nat, cc, prefix, cities, _w = rng.choices(NATIONALITIES, [n[4] for n in NATIONALITIES])[0]
    while True:
        phone = prefix + "".join(rng.choice("0123456789") for _ in range(8))
        if phone not in phones:
            phones.add(phone)
            break
    customers.append(dict(customer_id=uid(), display_name=f"{rng.choice(FIRST)} {rng.choice(LAST)}",
                          primary_phone_e164=phone, nationality=nat, residence_city=rng.choice(cities),
                          residence_country=cc, preferred_language="ar",
                          first_seen_at=None, last_seen_at=None))
# a slice of customers already existed before the window
for c in rng.sample(customers, 900):
    c["_pre"] = at(date(2025, 6, 1) + timedelta(days=rng.randrange(200)), rng.uniform(10, 23))

# --------------------------------------------------------------------------- calendar
RAMADAN = (date(2026, 2, 18), date(2026, 3, 19))
EID_FITR = (date(2026, 3, 20), date(2026, 3, 23))
SUMMER = (date(2026, 6, 15), date(2026, 8, 31))
NATIONAL_DAY = (date(2026, 9, 18), date(2026, 9, 24))


def within(d, span):
    return span[0] <= d <= span[1]


def day_weight(d: date) -> float:
    w = 1.0
    if within(d, RAMADAN):
        w *= 1.25
    if within(d, EID_FITR):
        w *= 1.6
    if within(d, SUMMER):
        w *= 1.55
    if within(d, NATIONAL_DAY):
        w *= 1.4
    if d.weekday() in (4, 5):   # Fri, Sat
        w *= 0.8
    return w


SERVICES = ["package", "flight", "hotel", "umrah", "visa", "insurance", "transfer", "cruise", "other"]


def service_for(d: date) -> str:
    w = [30, 22, 14, 8, 8, 3, 3, 1, 3]
    if within(d, RAMADAN):
        w[3] = 40
    if within(d, SUMMER):
        w[0] = 45
    return rng.choices(SERVICES, w)[0]


INTENTS = ["price_inquiry", "booking_request", "availability_check", "modification",
           "cancellation", "complaint", "visa_inquiry", "general_info"]
CHANNELS = ["whatsapp", "instagram", "facebook", "telegram", "webchat"]
CH_W = [70, 15, 7, 3, 5]

# --------------------------------------------------------------------------- conversations
days = [START + timedelta(days=i) for i in range((END - START).days + 1)]
weights = [day_weight(d) for d in days]
N_CONV = 15000
conv_days = sorted(rng.choices(days, weights, k=N_CONV))

interactions, metrics, analyses, legs, evaluations, follow_ups, deals = [], [], [], [], [], [], []
customer_pool = customers[:]
rng.shuffle(customer_pool)
returning: list[dict] = []
deal_by_customer: dict[str, dict] = {}


def pick_customer(n: int) -> dict:
    # new customers arrive evenly across the window; everyone else is a returning one
    p_new = len(customer_pool) / (N_CONV - n) if customer_pool else 0
    if customer_pool and (not returning or rng.random() < p_new):
        c = customer_pool.pop()
        returning.append(c)
        return c
    return rng.choice(returning)


def active_humans(d: date):
    return [a for a in humans if a["is_active"] or d < KHALED_LEFT]


def make_score(skill: float):
    base = rng.gauss(skill, 9)
    mods = {}
    for m, spread, null_p in [("m1_reception", 7, 0.0), ("m2_offer", 10, 0.1), ("m3_objections", 12, 0.55),
                              ("m4_followup", 11, 0.35), ("m5_closing", 12, 0.25)]:
        mods[m] = None if rng.random() < null_p else round(max(0, min(100, rng.gauss(base, spread))), 2)
    wts = {"m1_reception": .15, "m2_offer": .30, "m3_objections": .20, "m4_followup": .15, "m5_closing": .20}
    applied = sum(wts[m] for m, v in mods.items() if v is not None)
    final = round(sum(wts[m] * v for m, v in mods.items() if v is not None) / applied, 2)
    return mods, applied, final


def level(score):
    if score is None:
        return None
    return "Excellent" if score >= 85 else "Good" if score >= 70 else "Average" if score >= 55 else "Below Average"


AMOUNTS = {"package": (6000, 26000), "flight": (1200, 6500), "hotel": (900, 9000), "umrah": (2200, 9500),
           "visa": (300, 950), "insurance": (120, 450), "transfer": (150, 900), "cruise": (7000, 22000),
           "other": (300, 3000)}
OPEN_STAGES = ["NEW", "PREPARATION", "PREPAYMENT_INVOICE", "EXECUTING"]
PROMISES = ["أرسل لك العرض بكرة", "أتواصل معك بعد ما أتأكد من الأسعار", "أرسل لك تفاصيل الفندق",
            "أرجع لك بخصوص التأشيرة", "أكلمك بعد ساعتين"]

for n, d in enumerate(conv_days):
    cust = pick_customer(n)
    hour = rng.choices([rng.uniform(10, 22), rng.uniform(22, 24), rng.uniform(0, 10)], [80, 12, 8])[0]
    started = at(d, hour)
    after_hours = not (10 <= hour < 22)
    channel = rng.choices(CHANNELS, CH_W)[0]
    bot_handled = rng.random() < 0.18
    agent = bot if bot_handled else rng.choice(active_humans(d))
    msgs = rng.randint(2, 9) if bot_handled else rng.randint(3, 90)
    cust_msgs = max(1, round(msgs * rng.uniform(0.4, 0.6)))
    agent_msgs = msgs - cust_msgs
    if bot_handled:
        first_resp = rng.randint(2, 15)
    else:
        mean = agent["_speed"] * 60 * (4 if after_hours else 1)
        first_resp = int(min(6 * 3600, rng.expovariate(1 / mean) + 20))
    span = int(rng.uniform(5 * 60, 3 * 86400) if msgs > 20 else rng.uniform(3 * 60, 6 * 3600))
    ended = started + timedelta(seconds=span)
    iid = uid()
    cust["first_seen_at"] = cust.get("_pre") or min(filter(None, [cust["first_seen_at"], started]))
    cust["last_seen_at"] = max(filter(None, [cust["last_seen_at"], started]))
    service = service_for(d)
    row = dict(interaction_id=iid, customer_id=cust["customer_id"], agent_id=agent["agent_id"], deal_id=None,
               channel=channel, handled_by="bot" if bot_handled else "agent", is_bot_handled=bot_handled,
               external_id=f"chat-{100000 + n}", external_source="bitrix_openlines",
               customer_phone_e164=cust["primary_phone_e164"], started_at=started, ended_at=ended,
               message_count=msgs, customer_message_count=cust_msgs, agent_message_count=agent_msgs,
               first_response_seconds=first_resp, avg_response_seconds=int(first_resp * rng.uniform(0.8, 2.5)),
               is_after_hours=after_hours, external_deal_id=None)
    interactions.append(row)
    followup_count = 0 if bot_handled else rng.choices([0, 1, 2, 3], [50, 30, 15, 5])[0]
    metrics.append(dict(interaction_id=iid, first_response_seconds=first_resp,
                        median_response_seconds=int(first_resp * rng.uniform(0.6, 1.8)),
                        max_response_gap_seconds=int(first_resp * rng.uniform(2, 8)),
                        customer_message_count=cust_msgs, agent_message_count=agent_msgs,
                        conversation_span_seconds=span, after_hours=after_hours,
                        language_matched=rng.random() < 0.97, followup_count=followup_count,
                        hours_to_first_followup=round(rng.uniform(1, 72), 2) if followup_count else None))

    # ---- pass 1: what the customer wanted (90% of conversations)
    lead_temp = "unknown"
    if rng.random() < 0.9:
        aid = uid()
        lead_temp = rng.choices(["hot", "warm", "cold", "unknown"], [15, 35, 35, 15])[0]
        stage = rng.choices(["awareness", "consideration", "decision", "purchased", "lost", "unknown"],
                            [20, 35, 20, 8, 7, 10])[0]
        egp = cust["nationality"] == "Egyptian" and rng.random() < 0.6
        has_budget = rng.random() < 0.4
        lo, hi = AMOUNTS[service]
        trip_start = d + timedelta(days=rng.randint(5, 90))
        nights = rng.randint(2, 14)
        trav = rng.choices([1, 2, 3, 4, 5, 6, 8], [15, 30, 15, 20, 10, 6, 4])[0]
        children = rng.randint(0, max(0, trav - 2)) if trav > 2 else 0
        analyses.append(dict(analysis_id=aid, interaction_id=iid, model="deepseek-flash", language="ar",
                             intent=rng.choices(INTENTS, [30, 20, 15, 8, 5, 5, 7, 10])[0],
                             service=service, service_raw=None,
                             customer_nationality=cust["nationality"], residence_city=cust["residence_city"],
                             date_start=trip_start, date_end=trip_start + timedelta(days=nights), nights=nights,
                             travelers_total=trav, travelers_adults=trav - children, travelers_children=children,
                             budget_amount=(round(rng.uniform(lo, hi) * (6.5 if egp else 1), -1) if has_budget else None),
                             budget_currency=("EGP" if egp else "SAR") if has_budget else None,
                             buying_stage=stage, lead_temp=lead_temp, is_decision_maker=rng.random() < 0.8,
                             summary_ar=None, confidence=round(rng.uniform(0.6, 0.98), 2),
                             created_at=ended + timedelta(minutes=rng.randint(30, 600))))
        if service in ("package", "hotel", "flight", "umrah", "visa", "cruise"):
            if service == "umrah":
                trip = ["Makkah"] + (["Madinah"] if rng.random() < 0.6 else [])
            else:
                first = rng.choices([t[0] for t in TRIP_DESTS], [t[1] for t in TRIP_DESTS])[0]
                trip = [first]
                if first == "Istanbul" and rng.random() < 0.35:
                    trip.append(rng.choice(["Trabzon", "Bursa", "Antalya"]))
                if first == "Tbilisi" and rng.random() < 0.4:
                    trip.append("Batumi")
            origin = "Cairo" if cust["residence_country"] == "EG" else "Jeddah" if cust["residence_city"] == "Jeddah" else "Riyadh"
            if origin not in trip:
                legs.append(dict(id=len(legs) + 1, analysis_id=aid, destination_id=dest_id[origin],
                                 raw_name=dest_ar.get(origin, origin), role="origin", leg_order=0, nights=None))
            for k, t in enumerate(trip, start=1):
                legs.append(dict(id=len(legs) + 1, analysis_id=aid, destination_id=dest_id[t],
                                 raw_name=rng.choice([a["alias"] for a in aliases if a["destination_id"] == dest_id[t]]),
                                 role="destination", leg_order=k, nights=None))

    # a conversation during a live deal belongs to that deal
    existing = deal_by_customer.get(cust["customer_id"])
    if existing and (existing["close_date"] is None or existing["close_date"] >= d) \
            and (d - existing["begin_date"]).days <= 30 and rng.random() < 0.8:
        row["deal_id"] = existing["deal_id"]
        row["external_deal_id"] = existing["bitrix_deal_id"]

    if bot_handled:
        continue

    # ---- pass 2: agent quality (70% of human conversations with 4+ messages)
    if msgs >= 4 and rng.random() < 0.7:
        r = rng.random()
        status = "ok" if r < 0.92 else "contract_failed" if r < 0.95 else "ungradeable" if r < 0.99 else "unscoreable"
        mods, applied, final = make_score(agent["_skill"])
        gradeable = status != "ungradeable"
        if status != "ok":
            final = None if status in ("ungradeable", "unscoreable") else final
        evaluations.append(dict(evaluation_id=uid(), interaction_id=iid, agent_id=agent["agent_id"],
                                prompt_version="pass2-agent-quality-v7", rubric_version="qa-rubric-2026.1",
                                model="deepseek-flash", input_type="chat", final_score=final,
                                performance_level=level(final) if status == "ok" else None,
                                weight_applied=round(applied, 3), **mods,
                                stage_reached=rng.choice(["reception", "offer_presented", "negotiation",
                                                          "follow_up", "closing_attempted", "deal_closed"]),
                                top_strength=None, top_weakness=None, contract_status=status,
                                gradeable=gradeable, created_at=ended + timedelta(hours=rng.uniform(1, 30))))

    # ---- follow-up promises
    if agent_msgs >= 3 and rng.random() < 0.25:
        due = ended + timedelta(hours=rng.choice([2, 4, 24, 24, 48]))
        if due > TODAY:
            st, ff, hrs = "open", None, None
        else:
            r = rng.random()
            kept = agent["_disc"]
            if r < kept * 0.9:
                st = "fulfilled"
            elif r < kept * 0.9 + (1 - kept) * 0.45:
                st = "late"
            elif r < 0.97:
                st = "missed" if rng.random() < 0.75 else "open"   # 'open' past due = overdue
            else:
                st = "cancelled"
            if st == "fulfilled":
                ff = ended + (due - ended) * rng.uniform(0.2, 1.0)
            elif st == "late":
                ff = due + timedelta(hours=rng.uniform(1, 72))
            else:
                ff = None
            hrs = round((ff - ended).total_seconds() / 3600, 2) if ff else None
        follow_ups.append(dict(follow_up_id=uid(), customer_id=cust["customer_id"], agent_id=agent["agent_id"],
                               promised_in=iid, fulfilled_in=None, promise_text=rng.choice(PROMISES),
                               promised_at=ended, due_at=due, fulfilled_at=ff, hours_to_fulfil=hrs, status=st,
                               channel=channel))

    # ---- deals: a sales conversation about a bookable service may open one
    if agent["team"] == "sales" and service not in ("other",) and row["deal_id"] is None and rng.random() < 0.32:
        created = started + timedelta(minutes=rng.randint(5, 240))
        p_win = {"hot": 0.55, "warm": 0.32, "cold": 0.12, "unknown": 0.22}[lead_temp] * agent["_skill"] / 75
        lo, hi = AMOUNTS[service]
        amount = round(rng.uniform(lo, hi), -1)
        close = (created + timedelta(days=rng.randint(1, 21))).date()
        r = rng.random()
        if close >= TODAY.date() or r > 0.85:     # still open
            sem, stage_id, closed, close_date = "P", rng.choice(OPEN_STAGES), False, None
        elif r < p_win * 0.85:
            sem, stage_id, closed, close_date = "S", "WON", True, close
        else:
            sem, stage_id, closed, close_date = "F", "LOSE", True, close
        deal = dict(deal_id=uid(), bitrix_deal_id=str(40000 + len(deals)), customer_id=cust["customer_id"],
                    agent_id=agent["agent_id"],
                    title=f"{ {'package': 'باقة', 'flight': 'طيران', 'hotel': 'فندق', 'umrah': 'عمرة', 'visa': 'تأشيرة', 'insurance': 'تأمين', 'transfer': 'مواصلات', 'cruise': 'كروز'}[service]} - {cust['display_name']}",
                    category_id="0", stage_id=stage_id, stage_semantic=sem, is_closed=closed, amount=amount,
                    currency="SAR", source_channel=channel, service=service, lead_temp=lead_temp,
                    begin_date=created.date(), close_date=close_date, created_at_src=created,
                    modified_at_src=at(close_date, rng.uniform(10, 22)) if close_date else created,
                    origin="bitrix",
                    ai_outcome={"S": "won", "F": "lost", "P": "in_progress"}[sem])
        deals.append(deal)
        deal_by_customer[cust["customer_id"]] = deal
        row["deal_id"] = deal["deal_id"]
        row["external_deal_id"] = deal["bitrix_deal_id"]

# customers never contacted in the window keep their pre-window dates, or are dropped
customers = [c for c in customers if c["first_seen_at"] or c.get("_pre")]
for c in customers:
    c["first_seen_at"] = c["first_seen_at"] or c["_pre"]
    c["last_seen_at"] = c["last_seen_at"] or c["first_seen_at"]


def frame(rows):
    return pd.DataFrame([{k: v for k, v in r.items() if not k.startswith("_")} for r in rows])


TABLES = {
    "agents": frame(agents + [bot]), "customers": frame(customers), "destinations": frame(destinations),
    "destination_aliases": frame(aliases), "interactions": frame(interactions),
    "interaction_metrics": frame(metrics), "interaction_analysis": frame(analyses),
    "interaction_destinations": frame(legs), "agent_evaluations": frame(evaluations),
    "deals": frame(deals), "follow_ups": frame(follow_ups),
}

if __name__ == "__main__":
    DB_PATH.unlink(missing_ok=True)
    con = duckdb.connect(str(DB_PATH))
    con.execute("SET TimeZone = 'Asia/Riyadh'")
    con.execute((HERE / "schema.sql").read_text(encoding="utf-8"))
    for name, df in TABLES.items():
        cols = ", ".join(df.columns)
        con.register("df", df)
        con.execute(f"INSERT INTO {name} ({cols}) SELECT {cols} FROM df")
        con.unregister("df")
        print(f"{name:26s} {len(df):>6}")
    con.close()
