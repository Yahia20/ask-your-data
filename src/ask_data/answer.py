"""What the assistant hands back, and how numbers are written for a person."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Status = Literal["answered", "clarify", "refused", "unsure", "error"]
Tier = Literal["semantic", "verified", "voted"]

# Stored codes -> what a Saudi manager would say.
AR_VALUES = {
    "whatsapp": "واتساب", "instagram": "إنستغرام", "facebook": "فيسبوك", "telegram": "تيليجرام", "webchat": "دردشة الموقع",
    "package": "باقات", "flight": "طيران", "hotel": "فنادق", "umrah": "عمرة", "visa": "تأشيرات", "insurance": "تأمين",
    "transfer": "مواصلات", "cruise": "رحلات بحرية", "other": "أخرى", "unknown": "غير محدد",
    "hot": "ساخن", "warm": "دافئ", "cold": "بارد", "sales": "المبيعات", "support": "خدمة العملاء", "bot": "البوت",
    "won": "ناجحة", "lost": "خاسرة", "open": "مفتوحة", "fulfilled": "منفّذة", "late": "متأخرة", "missed": "فائتة",
    "cancelled": "ملغاة", "Excellent": "ممتاز", "Good": "جيد", "Average": "متوسط", "Below Average": "أقل من المتوسط",
    "price_inquiry": "استفسار عن السعر", "booking_request": "طلب حجز", "availability_check": "سؤال عن التوفر",
    "modification": "تعديل", "cancellation": "إلغاء", "complaint": "شكوى", "visa_inquiry": "استفسار تأشيرة",
    "general_info": "استفسار عام", "agent": "موظف",
    "awareness": "تعرّف", "consideration": "مقارنة", "decision": "قرار", "purchased": "اشترى",
    "Saudi": "سعودي", "Egyptian": "مصري", "Kuwaiti": "كويتي", "Emirati": "إماراتي", "Jordanian": "أردني", "Yemeni": "يمني",
    "Riyadh": "الرياض", "Jeddah": "جدة", "Dammam": "الدمام", "Makkah": "مكة", "Madinah": "المدينة", "Abha": "أبها",
    "Khobar": "الخبر", "Tabuk": "تبوك", "Cairo": "القاهرة", "Alexandria": "الإسكندرية", "Giza": "الجيزة",
    "Kuwait City": "الكويت", "Dubai": "دبي", "Abu Dhabi": "أبوظبي", "Amman": "عمّان",
    "Istanbul": "إسطنبول", "Trabzon": "طرابزون", "Bursa": "بورصة", "Antalya": "أنطاليا", "Sharm El Sheikh": "شرم الشيخ",
    "Baku": "باكو", "Tbilisi": "تبليسي", "Batumi": "باتومي", "Bosnia": "البوسنة", "Bali": "بالي", "Maldives": "المالديف",
    "Kuala Lumpur": "كوالالمبور", "London": "لندن", "Paris": "باريس", "Switzerland": "سويسرا",
    "Sunday": "الأحد", "Monday": "الاثنين", "Tuesday": "الثلاثاء", "Wednesday": "الأربعاء", "Thursday": "الخميس",
    "Friday": "الجمعة", "Saturday": "السبت",
}


@dataclass
class Answer:
    question: str
    status: Status
    lang: str = "ar"
    tier: Tier | None = None
    text: str = ""
    restated: str = ""
    columns: list[str] = field(default_factory=list)     # display labels
    rows: list[tuple] = field(default_factory=list)      # raw values (also what the grader reads)
    formats: list[str | None] = field(default_factory=list)
    sql: list[str] = field(default_factory=list)
    options: list[str] = field(default_factory=list)
    votes: str | None = None
    chart: dict | None = None
    cost_usd: float = 0.0
    seconds: float = 0.0
    route_trace: list[str] = field(default_factory=list)


def fmt(v, kind: str | None, lang: str) -> str:
    if v is None:
        return "—"
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, bool):
        return ("نعم" if v else "لا") if lang == "ar" else ("yes" if v else "no")
    if isinstance(v, (int, float)) or type(v).__name__ == "Decimal":
        x = float(v)
        if kind == "sar":
            return f"{x:,.0f} ريال" if lang == "ar" else f"SAR {x:,.0f}"
        if kind == "pct":
            return f"{x:.1f}%"
        if kind == "minutes":
            return f"{x:.1f} دقيقة" if lang == "ar" else f"{x:.1f} min"
        if kind in ("score", "dec"):
            return f"{x:.1f}"
        return f"{x:,.0f}" if x == int(x) else f"{x:,.2f}"
    s = str(v)
    return AR_VALUES.get(s, s) if lang == "ar" else s
