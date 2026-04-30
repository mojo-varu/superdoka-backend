"""
sandbox.py — Virtual Fleet Manager · Live Sandbox
===================================================
Calls the REAL EventProcessor, REAL NER model, REAL SQLite DB.
The only thing that differs from production is the input channel:
  Production:  MAX / Telegram message
  This demo:   Streamlit text input

Run:
    python demo_seed.py      # once — creates DB + seed data
    streamlit run sandbox.py

The NER model path is read from MODEL_DIR in app/core/ner_handler.py.
If the model is absent, the app boots but marks NER as unavailable and
routes all messages through the LLM fallback (set LLM_API_KEY in env).
"""

from __future__ import annotations

import asyncio
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

st.set_page_config(
    page_title  = "VFM Sandbox",
    page_icon   = "🚜",
    layout      = "wide",
    initial_sidebar_state = "expanded",
)

# ── Bootstrap DB + NER on first load ─────────────────────────────────────────

@st.cache_resource
def bootstrap():
    """Runs once per Streamlit process. Inits DB and starts NER loading."""
    async def _init():
        from app.db.database import init_db
        await init_db()

    asyncio.run(_init())

    # Start NER model loading (non-blocking background thread)
    try:
        from app.core.ner_handler import init_model
        init_model()
        return True
    except Exception:
        return False

_ner_started = bootstrap()

# ── Helpers ───────────────────────────────────────────────────────────────────

def run_async(coro):
    """Run an async coroutine from sync Streamlit context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def ner_status() -> tuple[bool, str]:
    try:
        from app.core.ner_handler import is_model_ready, model_load_error
        if model_load_error:
            return False, f"Model error: {model_load_error}"
        return is_model_ready(), "Ready" if is_model_ready() else "Loading..."
    except Exception as e:
        return False, str(e)


# ── DB read helpers ───────────────────────────────────────────────────────────

async def _get_machines():
    from app.db.database import AsyncSessionLocal
    from app.db.models import Machine, MachineState
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(Machine, MachineState)
            .outerjoin(MachineState, MachineState.machine_id == Machine.id)
            .where(Machine.is_active == True)
        )
        return r.all()


async def _get_operators():
    from app.db.database import AsyncSessionLocal
    from app.db.models import User
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(User).where(User.user_type == "OPERATOR", User.is_active == True)
        )
        return r.scalars().all()


async def _get_timeline(limit: int = 40):
    from app.db.database import AsyncSessionLocal
    from app.db.models import TimelineEvent, Machine, User
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(TimelineEvent, Machine.reg_number, User.name)
            .join(Machine, Machine.id == TimelineEvent.machine_id)
            .outerjoin(User, User.id == TimelineEvent.operator_id)
            .order_by(TimelineEvent.created_at.desc())
            .limit(limit)
        )
        return r.all()


async def _get_active_sessions():
    from app.db.database import AsyncSessionLocal
    from app.db.models import ActiveSession, Machine, User
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(ActiveSession, Machine.reg_number, User.name)
            .join(Machine, Machine.id == ActiveSession.machine_id)
            .join(User, User.id == ActiveSession.operator_id)
            .where(ActiveSession.shift_state == "ACTIVE")
        )
        return r.all()


async def _process_message(operator_tg_id: str, chat_id: str, text: str):
    from app.db.database import AsyncSessionLocal
    from app.schemas.fleet_update import FleetUpdate, MessageSource, Modality
    from app.services.event_processor import EventProcessor

    update = FleetUpdate.from_raw(
        source         = MessageSource.TELEGRAM,
        operator_tg_id = operator_tg_id,
        chat_id        = chat_id,
        raw_text       = text,
        modality       = Modality.TEXT,
    )

    processor = EventProcessor()
    async with AsyncSessionLocal() as db:
        result = await processor.process(db, update)
    return result


# ── CSS ───────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
.main .block-container{padding-top:1rem;max-width:1400px}
.metric-card{background:#f8f8f6;border:0.5px solid #e0dfd8;border-radius:8px;
             padding:12px 16px;margin:4px 0}
.tl-row{border-left:3px solid #e0dfd8;padding:6px 12px;margin:4px 0;
        font-size:13px;line-height:1.6}
.tl-fuel{border-color:#378ADD}
.tl-hours{border-color:#1D9E75}
.tl-issue{border-color:#E24B4A}
.tl-shift{border-color:#7F77DD}
.tl-other{border-color:#888780}
.badge{display:inline-block;padding:2px 9px;border-radius:4px;
       font-size:11px;font-weight:500;margin-right:4px}
.conf-bar-wrap{background:#f0efea;border-radius:3px;height:5px;
               display:inline-block;width:80px;vertical-align:middle;margin:0 6px}
.reply-box{background:#E1F5EE;border:0.5px solid #9FE1CB;border-radius:8px;
           padding:10px 16px;font-size:15px;margin:8px 0}
.alert-box{background:#FCEBEB;border:0.5px solid #F7C1C1;border-radius:8px;
           padding:10px 16px;font-size:14px;margin:6px 0}
</style>
""", unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### 🚜 VFM Sandbox")
    st.caption("Real backend · Real NER · Real DB")

    ner_ready, ner_msg = ner_status()
    if ner_ready:
        st.success(f"NER model ready", icon="✓")
    else:
        st.warning(f"NER: {ner_msg}", icon="⚠")

    st.divider()
    st.markdown("**Act as**")
    role = st.radio("Role", ["Operator", "Owner"], horizontal=True, label_visibility="collapsed")

    operators = run_async(_get_operators())
    op_names  = {f"{op.name} (ID {op.telegram_id})": str(op.telegram_id) for op in operators}

    if role == "Operator":
        selected_label = st.selectbox("Select operator", list(op_names.keys()))
        operator_tg_id = op_names[selected_label]
    else:
        operator_tg_id = "100001"  # owner tg_id from seed

    st.divider()
    st.markdown("**Demo scripts**")

    SCRIPTS = {
        "Normal shift": [
            ("200001", "Начинаю смену на CAT-101"),
            ("200001", "Залил 50 литров"),
            ("200001", "Наработка 6 часов"),
            ("200001", "Смена закончена"),
        ],
        "Fuel anomaly": [
            ("200002", "Начинаю смену на BLZ-042"),
            ("200002", "Залил 300 литров"),
        ],
        "Critical issue": [
            ("200003", "Начинаю смену на KOM-007"),
            ("200003", "Пожар в кабине, срочно!"),
        ],
        "Repeated faults": [
            ("200001", "Начинаю смену на CAT-101"),
            ("200001", "Течь масла небольшая"),
            ("200001", "Стук в двигателе"),
            ("200001", "Гидравлика слабо работает"),
        ],
    }

    for script_name, steps in SCRIPTS.items():
        if st.button(f"▶ {script_name}", use_container_width=True):
            st.session_state["script_queue"] = steps
            st.session_state["script_name"]  = script_name
            st.rerun()

    st.divider()
    if st.button("🗑 Reset demo DB", use_container_width=True, type="secondary"):
        if Path("vfm_demo.db").exists():
            os.remove("vfm_demo.db")
        st.cache_resource.clear()
        st.session_state.clear()
        st.rerun()

# ── Main layout: 3 columns ────────────────────────────────────────────────────

col_input, col_fleet, col_timeline = st.columns([1.1, 0.9, 1], gap="medium")

# ── Col 1: Message input + pipeline result ────────────────────────────────────

with col_input:
    st.markdown("#### Send a message")

    # Run a script step if queued
    if "script_queue" in st.session_state and st.session_state.script_queue:
        steps = st.session_state.script_queue
        op_id, preset_text = steps.pop(0)
        if not steps:
            del st.session_state["script_queue"]
        st.session_state["auto_send"] = (op_id, preset_text)
        st.rerun()

    with st.form("send_form", clear_on_submit=True):
        user_text = st.text_area(
            "Message",
            height=90,
            placeholder="Введите сообщение по-русски...\n\nПримеры:\n• Начинаю смену на CAT-101\n• Залил 50 литров\n• Течь масла — срочно",
            label_visibility="collapsed",
        )
        col_btn1, col_btn2 = st.columns([1, 1])
        with col_btn1:
            send = st.form_submit_button("Send →", use_container_width=True, type="primary")
        with col_btn2:
            st.form_submit_button("Clear", use_container_width=True)

    # Handle auto-send from script
    auto = st.session_state.pop("auto_send", None)
    if auto:
        auto_op_id, auto_text = auto
        st.info(f"Running script step: **{auto_text}** (operator {auto_op_id})")
        send      = True
        user_text = auto_text
        operator_tg_id = auto_op_id

    # Process the message
    if send and user_text and user_text.strip():
        with st.spinner("Running pipeline..."):
            result = run_async(_process_message(
                operator_tg_id = operator_tg_id,
                chat_id        = f"demo_chat_{operator_tg_id}",
                text           = user_text.strip(),
            ))
        st.session_state["last_result"] = result

    # Display pipeline result
    res = st.session_state.get("last_result")
    if res:
        st.divider()

        # Bot reply
        if res.reply_text:
            st.markdown(
                f'<div class="reply-box">🤖 {res.reply_text}</div>',
                unsafe_allow_html=True,
            )

        # Alerts from rules
        for action in res.actions:
            if action.action_type in ("alert_owner", "alert_mechanic"):
                st.markdown(
                    f'<div class="alert-box">🔔 <b>{action.action_type}</b>: {action.message}</div>',
                    unsafe_allow_html=True,
                )

        # Pipeline breakdown
        st.markdown("**Pipeline breakdown**")

        # Confidence bar
        conf_pct  = int(res.confidence * 100)
        conf_col  = "#1D9E75" if conf_pct >= 85 else ("#BA7517" if conf_pct >= 60 else "#E24B4A")
        route_colors = {"auto": "#E1F5EE", "confirm": "#FAEEDA", "llm": "#FCEBEB"}
        r_bg = route_colors.get(str(res.confidence_route).lower(), "#F1EFE8")

        c1, c2, c3 = st.columns(3)
        c1.metric("Intent",     res.intent)
        c2.metric("Confidence", f"{conf_pct}%",  delta=res.confidence_route)
        c3.metric("Via LLM",    "Yes" if res.via_llm else "No")

        if res.entities:
            st.markdown("**Extracted entities**")
            ent_items = {k: v for k, v in res.entities.items()
                         if k not in ("workflow",) and v is not None}
            if ent_items:
                cols = st.columns(min(len(ent_items), 4))
                for i, (k, v) in enumerate(ent_items.items()):
                    cols[i % len(cols)].metric(k, str(v))

        if res.rules_fired:
            st.markdown("**Rules fired**")
            for rule_id in res.rules_fired:
                st.error(f"⚡ `{rule_id}`")
        else:
            st.success("No rules fired — within normal parameters", icon="✓")

        if res.processing_errors:
            with st.expander("Processing errors"):
                for e in res.processing_errors:
                    st.error(e)

        with st.expander("Full FleetUpdate JSON"):
            import json
            st.code(json.dumps({
                "update_id":          res.update_id,
                "source":             str(res.source),
                "operator_tg_id":     res.operator_tg_id,
                "intent":             str(res.intent),
                "confidence":         round(res.confidence, 4),
                "confidence_route":   str(res.confidence_route),
                "via_llm":            res.via_llm,
                "entities":           res.entities,
                "raw_entities":       res.raw_entities,
                "machine_id":         res.machine_id,
                "session": {
                    "machine_reg":        res.session.machine_reg_number if res.session else None,
                    "minutes_on_shift":   res.session.minutes_on_shift   if res.session else None,
                    "fuel_logged_today":  res.session.fuel_logged_today   if res.session else None,
                    "hours_logged_today": res.session.hours_logged_today  if res.session else None,
                    "open_issues":        res.session.open_issue_count    if res.session else None,
                } if res.session else None,
                "timeline_event_id":  res.timeline_event_id,
                "rules_fired":        res.rules_fired,
                "actions": [
                    {"type": a.action_type, "priority": a.priority, "message": a.message}
                    for a in res.actions
                ],
                "reply_text":         res.reply_text,
                "needs_confirmation": res.needs_confirmation,
                "processing_errors":  res.processing_errors,
            }, ensure_ascii=False, indent=2), language="json")

# ── Col 2: Live fleet state ────────────────────────────────────────────────────

with col_fleet:
    st.markdown("#### Fleet state")

    machines_data = run_async(_get_machines())
    active_sessions = run_async(_get_active_sessions())
    active_machine_ids = {s[0].machine_id for s in active_sessions}

    STATUS_STYLE = {
        "IDLE":        ("⚪", "#F1EFE8", "#5F5E5A"),
        "WORKING":     ("🟢", "#E1F5EE", "#085041"),
        "WARNING":     ("🟡", "#FAEEDA", "#633806"),
        "DOWN":        ("🔴", "#FCEBEB", "#A32D2D"),
        "MAINTENANCE": ("🔵", "#EEEDFE", "#3C3489"),
    }

    for machine, state in machines_data:
        status = state.status if state else "IDLE"
        icon, bg, fg = STATUS_STYLE.get(status, STATUS_STYLE["IDLE"])
        on_shift = machine.id in active_machine_ids
        shift_op = next(
            (s[2] for s in active_sessions if s[0].machine_id == machine.id), None
        )

        fuel   = state.fuel_added_today   if state else 0
        hours  = state.hours_worked_today if state else 0
        issues = state.open_issue_count   if state else 0

        st.markdown(f"""
        <div class="metric-card">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <span style="font-weight:500;font-size:15px">{icon} {machine.reg_number}</span>
            <span class="badge" style="background:{bg};color:{fg}">{status}</span>
          </div>
          <div style="font-size:12px;color:#888780;margin-top:2px">{machine.machine_type} · {machine.model}</div>
          <div style="display:flex;gap:16px;margin-top:8px;font-size:13px">
            <div><span style="color:#888780">Топливо</span><br><b>{fuel:.0f}л</b></div>
            <div><span style="color:#888780">Наработка</span><br><b>{hours:.1f}ч</b></div>
            <div><span style="color:#888780">Проблемы</span><br>
              <b style="color:{'#E24B4A' if issues > 0 else 'inherit'}">{issues}</b>
            </div>
          </div>
          {"<div style='font-size:12px;color:#1D9E75;margin-top:6px'>👷 " + shift_op + " — активная смена</div>" if shift_op else ""}
        </div>
        """, unsafe_allow_html=True)

    st.divider()
    st.markdown("**Active sessions**")

    if active_sessions:
        for sess, reg, op_name in active_sessions:
            mins = int((datetime.utcnow() - sess.started_at).total_seconds() / 60)
            st.markdown(f"""
            <div class="metric-card">
              <b>{op_name}</b> → {reg}<br>
              <span style="font-size:12px;color:#888780">
                {mins} мин в смене ·
                {sess.fuel_logged_this_shift:.0f}л топлива ·
                {sess.hours_logged_this_shift:.1f}ч ·
                {sess.checkin_count} сообщений
              </span>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.caption("Нет активных смен")

    # Refresh button
    if st.button("↻ Refresh fleet", use_container_width=True):
        st.rerun()

# ── Col 3: Timeline ────────────────────────────────────────────────────────────

with col_timeline:
    st.markdown("#### Event timeline")
    st.caption("Live from timeline_events table")

    TL_STYLE = {
        "FUEL_LOG":         ("tl-fuel",   "⛽"),
        "HOURS_LOG":        ("tl-hours",  "⏱"),
        "ISSUE_REPORT":     ("tl-issue",  "⚠"),
        "SHIFT_START":      ("tl-shift",  "▶"),
        "SHIFT_END":        ("tl-shift",  "■"),
        "WATCHER_ALERT":    ("tl-issue",  "🔔"),
        "CORRECTION":       ("tl-other",  "✏"),
        "STATUS_UPDATE":    ("tl-other",  "●"),
        "INSPECTION_CHECK": ("tl-hours",  "✓"),
        "PARTS_REQUEST":    ("tl-other",  "🔧"),
    }

    timeline = run_async(_get_timeline(40))

    if not timeline:
        st.caption("No events yet. Send a message to create timeline entries.")
    else:
        for event, reg, op_name in timeline:
            css_class, icon = TL_STYLE.get(event.event_type, ("tl-other", "•"))
            ts    = event.created_at.strftime("%H:%M:%S")
            conf  = f"{int(event.confidence * 100)}%" if event.confidence else "—"
            llm   = " · via LLM" if event.via_llm else ""
            content = ""
            if event.content:
                snippets = []
                for k, v in event.content.items():
                    if v is not None and k not in ("description",):
                        snippets.append(f"{k}: <b>{v}</b>")
                if snippets:
                    content = " · ".join(snippets[:3])

            st.markdown(f"""
            <div class="tl-row {css_class}">
              <span style="color:#888780;font-size:11px">{ts}</span>
              <b> {icon} {event.event_type}</b>
              <span style="font-size:11px;color:#888780"> · {reg} · {op_name or '—'} · conf {conf}{llm}</span>
              {"<br><span style='color:#444441'>" + content + "</span>" if content else ""}
              {"<br><span style='color:#E24B4A;font-size:11px'>" + str(event.content.get('description',''))[:80] + "...</span>" if event.event_type == 'ISSUE_REPORT' and event.content.get('description') else ""}
            </div>
            """, unsafe_allow_html=True)

    if st.button("↻ Refresh timeline", use_container_width=True):
        st.rerun()

# ── Auto-advance script if queued ─────────────────────────────────────────────
if "script_queue" in st.session_state and st.session_state.script_queue:
    import time
    time.sleep(0.8)
    st.rerun()
