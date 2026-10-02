"""Chat UI.   streamlit run app.py"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))

from ask_data.answer import fmt  # noqa: E402
from ask_data.config import settings  # noqa: E402
from ask_data.pipeline import build  # noqa: E402

EXAMPLES = [
    "كم دخلنا الشهر اللي فات؟",
    "مين أشطر موظف مبيعات هالسنة؟",
    "وش أكثر وجهة يسألون عنها الناس هالسنة؟",
    "كيف مبيعاتنا شهر بشهر هالسنة؟",
    "عطني متوسط تقييم الجودة لكل موظف هالسنة",
    "كم متابعة متأخرة للحين؟",
    "قارن لي عدد محادثات هالشهر بالشهر اللي فات",
    "مين أحسن موظف؟",
]

st.set_page_config(page_title="اسأل بياناتك", page_icon="📊", layout="wide")
st.markdown("""<style>
  .stApp, .stChatMessage, .stMarkdown, .stButton, [data-testid="stSidebar"] { direction: rtl; text-align: right; }
  .stDataFrame, code, pre { direction: ltr; text-align: left; }
  .tier { display:inline-block; padding:2px 10px; border-radius:12px; font-size:0.8rem; margin-inline-start:6px; }
  .ok { background:#e6f4ea; color:#137333; } .warn { background:#fef7e0; color:#8a5a00; }
  .ask { background:#e8f0fe; color:#1a56c4; } .no { background:#f1f3f4; color:#3c4043; }
</style>""", unsafe_allow_html=True)


@st.cache_resource
def assistant():
    if not settings.database_url and not settings.demo_db.exists():
        subprocess.run([sys.executable, str(ROOT / "data" / "generate.py")], check=True)
    return build(settings)


def badge(a) -> str:
    if a.status == "clarify":
        return '<span class="tier ask">يحتاج توضيح</span>'
    if a.status in ("refused", "unsure", "error"):
        return '<span class="tier no">بدون رقم</span>'
    if a.tier in ("semantic", "verified"):
        return '<span class="tier ok">✅ موثّق</span>'
    return f'<span class="tier warn">⚠️ غير موثّق · اتفقت {a.votes} محاولات</span>'


def show(a, key: str):
    st.markdown(a.text + " " + badge(a), unsafe_allow_html=True)
    if a.status == "answered" and a.restated and a.restated not in a.text:
        st.caption(f"فهمت سؤالك كـ: {a.restated}")
    if a.status == "clarify" and a.options:
        cols = st.columns(len(a.options))
        for i, opt in enumerate(a.options):
            if cols[i].button(opt, key=f"{key}-opt-{i}"):
                st.session_state.pending = f"{a.question} ({opt})"
                st.rerun()
    if a.status == "answered" and (len(a.rows) > 1 or len(a.columns) > 2):
        df = pd.DataFrame(a.rows, columns=a.columns)
        shown = df.copy()
        for i, c in enumerate(shown.columns):
            f = a.formats[i] if i < len(a.formats) else None
            f = "int" if f == "sar" else "dec" if f == "minutes" else f   # the unit is in the column header
            shown[c] = [fmt(v, f, a.lang) for v in df.iloc[:, i]]
        st.dataframe(shown, hide_index=True, use_container_width=True)
        if a.chart:
            x, y = df.columns[a.chart["x"]], df.columns[a.chart["y"]]
            plot = df.assign(**{x: [fmt(v, None, a.lang) for v in df[x]]})
            plot[y] = pd.to_numeric(plot[y], errors="coerce")
            fig = (px.line if a.chart["kind"] == "line" else px.bar)(plot, x=x, y=y)
            fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True, key=f"{key}-chart")
    if a.sql:
        with st.expander("الاستعلام اللي اتنفّذ (SQL)"):
            for s in a.sql:
                st.code(s, language="sql")
    st.caption(f"⏱️ {a.seconds} ث · 💵 ${a.cost_usd:.4f}")


bot = assistant()
with st.sidebar:
    st.header("📊 اسأل بياناتك")
    st.write("اسأل عن المحادثات والصفقات والتقييمات والمتابعات، بالفصحى أو باللهجة السعودية.")
    st.caption(f"البيانات: {'قاعدة حيّة' if settings.database_url else 'بيانات تجريبية وهمية'} · اليوم: {bot.today}")
    st.subheader("جرّب")
    for q in EXAMPLES:
        if st.button(q, key=f"ex-{q}", use_container_width=True):
            st.session_state.pending = q
    st.divider()
    st.caption("✅ موثّق = محسوب من تعريفات معتمدة. ⚠️ غير موثّق = كتبه النموذج، ويظهر فقط إذا اتفقت أغلب المحاولات.")

st.session_state.setdefault("history", [])
if "q" in st.query_params and not st.session_state.history and "pending" not in st.session_state:
    st.session_state.pending = st.query_params["q"]     # shareable link: ?q=كم دخلنا الشهر اللي فات؟
for i, a in enumerate(st.session_state.history):
    with st.chat_message("user"):
        st.write(a.question)
    with st.chat_message("assistant"):
        show(a, f"h{i}")

question = st.chat_input("اكتب سؤالك... مثلًا: كم صفقة قفلناها الشهر اللي فات؟")
question = question or st.session_state.pop("pending", None)
if question:
    with st.chat_message("user"):
        st.write(question)
    with st.chat_message("assistant"):
        with st.spinner("أحسب..."):
            ans = bot.ask(question)
        show(ans, f"h{len(st.session_state.history)}")
    st.session_state.history.append(ans)
