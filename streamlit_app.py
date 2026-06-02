"""Streamlit UI for Data Warehouse Builder.

Run from the project root::

    streamlit run streamlit_app.py

Default mode uses local files (``STORAGE_BACKEND=file``). Set ``STORAGE_BACKEND=mysql``
when MySQL is ready.
"""

from __future__ import annotations

import json
import traceback
from pathlib import Path

import pandas as pd
import streamlit as st

from app.core.app_backend import get_file_pipeline, list_batches, pipeline_context, upload_context, use_file_storage
from app.core.config import settings
from app.core.exceptions import AppError

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Data Warehouse Builder",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="expanded",
)

SEVERITY_COLORS = {
    "Critical": "#dc3545",
    "High": "#fd7e14",
    "Medium": "#ffc107",
    "Low": "#17a2b8",
    "Info": "#6c757d",
}

STAGE_ORDER = (
    "uploaded",
    "bronze_done",
    "silver_done",
    "awaiting_approval",
    "gold_done",
)

STAGE_LABELS = {
    "uploaded": "Upload",
    "bronze_done": "Bronze",
    "silver_done": "Silver",
    "awaiting_approval": "Relationships",
    "relationships_detected": "Relationships",
    "gold_done": "Gold",
}

STAGE_ICONS = {
    "uploaded": "📤",
    "bronze_done": "🥉",
    "silver_done": "🥈",
    "awaiting_approval": "🔗",
    "relationships_detected": "🔗",
    "gold_done": "🥇",
}

NEXT_ACTIONS = {
    "uploaded": ("Run Bronze", "Go to **Pipeline** and click **Bronze** or **Full run**."),
    "bronze_done": ("Build Silver", "Bronze is ready — run **Silver** or **Full run**."),
    "silver_done": ("Detect relationships", "Run **Detect relationships**, then review on the Relationships tab."),
    "awaiting_approval": ("Approve & build Gold", "Review suggestions, approve links, then **Build Gold**."),
    "relationships_detected": ("Approve & build Gold", "Review suggestions, approve links, then **Build Gold**."),
    "gold_done": ("Download files", "Open **Files** to download cleaned CSVs or the full ZIP."),
}


def _inject_custom_css() -> None:
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.25rem; max-width: 1400px; }
        .dw-hero {
            background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 55%, #60a5fa 100%);
            border-radius: 12px; padding: 1.5rem 1.75rem; color: #fff;
            margin-bottom: 1rem; box-shadow: 0 4px 14px rgba(37,99,235,.25);
        }
        .dw-hero h2 { margin: 0 0 .35rem 0; font-size: 1.35rem; font-weight: 700; color: #fff; }
        .dw-hero p { margin: 0; opacity: .92; font-size: .95rem; }
        .dw-stepper { display: flex; gap: .35rem; flex-wrap: wrap; margin: .75rem 0 1rem 0; }
        .dw-step {
            flex: 1; min-width: 100px; text-align: center; padding: .55rem .5rem;
            border-radius: 8px; font-size: .78rem; font-weight: 600;
            border: 1px solid #e2e8f0; background: #f1f5f9; color: #64748b;
        }
        .dw-step.done { background: #dcfce7; border-color: #86efac; color: #166534; }
        .dw-step.active { background: #dbeafe; border-color: #93c5fd; color: #1e40af; }
        .dw-step.pending { background: #f8fafc; border-color: #e2e8f0; color: #94a3b8; }
        .dw-step.running { background: #fef9c3; border-color: #fde047; color: #854d0e; }
        .dw-step.failed { background: #fee2e2; border-color: #fca5a5; color: #991b1b; }
        .dw-step .icon { font-size: 1.1rem; display: block; margin-bottom: .15rem; }
        .dw-cta {
            background: #eff6ff; border-left: 4px solid #3b82f6;
            padding: .85rem 1rem; border-radius: 0 8px 8px 0; margin: .5rem 0 1rem 0;
        }
        .dw-cta strong { color: #1e40af; }
        .dw-chip {
            display: inline-block; background: #e0e7ff; color: #3730a3;
            padding: .2rem .65rem; border-radius: 999px; font-size: .8rem;
            font-weight: 600; margin-right: .35rem;
        }
        .dw-format-pill {
            display: inline-block; background: #f1f5f9; border: 1px solid #e2e8f0;
            padding: .15rem .5rem; border-radius: 6px; font-size: .75rem;
            margin: .15rem .25rem .15rem 0; color: #475569;
        }
        div[data-testid="stSidebar"] { background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%); }
        div[data-testid="stMetric"] {
            background: #fff; border: 1px solid #e2e8f0; border-radius: 10px;
            padding: .5rem .75rem; box-shadow: 0 1px 2px rgba(0,0,0,.04);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _normalize_stage(stage: str) -> str:
    if stage in ("awaiting_approval", "relationships_detected"):
        return "awaiting_approval"
    if stage not in STAGE_ORDER:
        return "uploaded"
    return stage


def _render_stepper(current_stage: str) -> None:
    stage = _normalize_stage(current_stage)
    idx = STAGE_ORDER.index(stage) if stage in STAGE_ORDER else 0
    steps_html = []
    for i, key in enumerate(STAGE_ORDER):
        icon = STAGE_ICONS.get(key, "•")
        label = STAGE_LABELS.get(key, key)
        cls = "dw-step"
        if i < idx:
            cls += " done"
        elif i == idx:
            cls += " active"
        steps_html.append(f'<div class="{cls}"><span class="icon">{icon}</span>{label}</div>')
    st.markdown(f'<div class="dw-stepper">{"".join(steps_html)}</div>', unsafe_allow_html=True)


def _render_next_action(current_stage: str) -> None:
    stage = _normalize_stage(current_stage)
    title, body = NEXT_ACTIONS.get(stage, ("Continue", "Use the tabs above to proceed."))
    st.markdown(
        f'<div class="dw-cta"><strong>Next:</strong> {title} — {body}</div>',
        unsafe_allow_html=True,
    )


def _load_status(batch_id: str):
    with pipeline_context() as svc:
        return svc.status(batch_id)


def _init() -> None:
    if "initialized" not in st.session_state:
        if not use_file_storage():
            try:
                from app.core.database import init_metadata_tables
                init_metadata_tables()
            except Exception:
                pass
        st.session_state.initialized = True
    if "batch_id" not in st.session_state:
        st.session_state.batch_id = None
    if "pipeline_running_step" not in st.session_state:
        st.session_state.pipeline_running_step = None


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} TB"


def _show_error(exc: Exception) -> None:
    if isinstance(exc, AppError):
        st.error(f"**{exc.code}**: {exc.message}")
        if exc.details:
            st.json(exc.details)
    else:
        st.error(str(exc))
        with st.expander("Traceback"):
            st.code(traceback.format_exc())


BATCH_PICKER_PLACEHOLDER = "— Select or create —"
_BATCH_PICKER_SYNC_KEY = "_batch_picker_target"


def _list_batches(*, force_refresh: bool = False) -> list[str]:
    if force_refresh:
        _cached_list_batches.clear()
    return _cached_list_batches()


@st.cache_data(ttl=5, show_spinner=False)
def _cached_list_batches() -> list[str]:
    return list_batches()


def _invalidate_batch_cache() -> None:
    _cached_list_batches.clear()


def _set_active_batch(batch_id: str | None) -> None:
    """Select a batch in session state and sync the sidebar selectbox."""
    _invalidate_batch_cache()
    st.session_state.batch_id = batch_id
    # Do NOT write to st.session_state.batch_picker here: if the selectbox has already been
    # instantiated earlier in this run, Streamlit will raise:
    # "st.session_state.<key> cannot be modified after the widget ... is instantiated."
    # Instead, stash the desired value and let the sidebar apply it before creating the widget.
    st.session_state[_BATCH_PICKER_SYNC_KEY] = batch_id if batch_id else BATCH_PICKER_PLACEHOLDER


def _batch_select_options() -> list[str]:
    """Batch IDs for the sidebar, including the active batch if not yet listed."""
    batches = _list_batches()
    active = st.session_state.get("batch_id")
    if active and active not in batches:
        batches = [active, *batches]
    return batches


def _check_mysql() -> tuple[bool, str]:
    return _cached_mysql_check()


@st.cache_data(ttl=15, show_spinner=False)
def _cached_mysql_check() -> tuple[bool, str]:
    try:
        from sqlalchemy import text
        from app.core.database import metadata_engine
        with metadata_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, f"Connected as `{settings.mysql_user}` @ `{settings.mysql_host}`"
    except Exception as exc:
        return False, str(exc)


def _safe_dataframe(df: pd.DataFrame, *, max_rows: int = 200) -> None:
    """Render a dataframe with a row cap to avoid huge websocket payloads."""
    if df.empty:
        st.info("No rows to display.")
        return
    if len(df) > max_rows:
        st.caption(f"Showing first {max_rows} of {len(df)} rows.")
        df = df.head(max_rows)
    st.dataframe(df, use_container_width=True)


def _sidebar() -> str | None:
    with st.sidebar:
        st.markdown("### 🏗️ DW Builder")
        st.caption("Raw → Bronze → Silver → Gold")

        if use_file_storage():
            st.success("📁 File mode — no MySQL")
            st.caption("Data saved under storage/batches/")
        else:
            mysql_ok, mysql_msg = _check_mysql()
            if mysql_ok:
                st.success("MySQL connected")
            else:
                st.error("MySQL offline")
                with st.expander("Fix connection"):
                    st.caption(mysql_msg[:200])
                    st.code("STORAGE_BACKEND=file", language="ini")

        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("🔄 Refresh", use_container_width=True, key="sidebar_refresh"):
                _invalidate_batch_cache()
                if st.session_state.get("batch_id"):
                    st.session_state[_BATCH_PICKER_SYNC_KEY] = st.session_state.batch_id
                st.rerun()
        with col_b:
            if st.button("➕ New batch", use_container_width=True, key="sidebar_new_batch"):
                _set_active_batch(None)
                st.rerun()

        st.divider()

        batches = _batch_select_options()
        options = [BATCH_PICKER_PLACEHOLDER] + batches

        # Apply any programmatic "pick this batch" request *before* the widget is created.
        if _BATCH_PICKER_SYNC_KEY in st.session_state:
            st.session_state.batch_picker = st.session_state[_BATCH_PICKER_SYNC_KEY]
            del st.session_state[_BATCH_PICKER_SYNC_KEY]

        if "batch_picker" not in st.session_state:
            st.session_state.batch_picker = BATCH_PICKER_PLACEHOLDER

        # Keep selectbox aligned when batch_id was set by upload / pipeline
        active = st.session_state.get("batch_id")
        if active and active in options and st.session_state.batch_picker != active:
            st.session_state.batch_picker = active

        picked = st.selectbox(
            "Active batch",
            options,
            key="batch_picker",
            help=f"{len(batches)} batch(es) available",
        )
        if picked != BATCH_PICKER_PLACEHOLDER:
            st.session_state.batch_id = picked
        elif st.session_state.get("batch_id") and st.session_state.batch_id not in batches:
            pass  # keep programmatic selection until folder/DB catches up
        else:
            st.session_state.batch_id = None

        batch_id = st.session_state.batch_id
        if batch_id:
            try:
                status = _load_status(batch_id)
                stage = _normalize_stage(status.current_stage)
                st.markdown(
                    f'<span class="dw-chip">{STAGE_ICONS.get(stage, "•")} '
                    f'{STAGE_LABELS.get(stage, stage)}</span>',
                    unsafe_allow_html=True,
                )
                st.caption(f"`{batch_id[:20]}…`" if len(batch_id) > 22 else f"`{batch_id}`")
                st.progress(
                    (STAGE_ORDER.index(stage) + 1) / len(STAGE_ORDER),
                    text=f"Step {STAGE_ORDER.index(stage) + 1} of {len(STAGE_ORDER)}",
                )
            except Exception:
                st.caption(f"Batch: `{batch_id}`")

        with st.expander("Storage paths", expanded=False):
            st.code(str(settings.storage_root), language="text")
            st.caption(f"Backend: **{settings.storage_backend}**")

    return st.session_state.batch_id


def _render_status(batch_id: str) -> None:
    try:
        status = _load_status(batch_id)
    except Exception as exc:
        st.warning(f"Could not load status: {exc}")
        return

    _render_stepper(status.current_stage)
    _render_next_action(status.current_stage)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Bronze", len(status.bronze_tables), help="Raw ingested tables")
    c2.metric("Silver", len(status.silver_tables), help="Cleaned & typed tables")
    c3.metric("Gold", len(status.gold_tables), help="Analytics-ready tables")
    c4.metric("Relationships", status.suggestion_count, delta=f"{status.approved_count} approved")
    c5.metric("Quality issues", status.quality_issue_count, help="Data quality findings")


# ---------------------------------------------------------------------------
# Tab: Upload
# ---------------------------------------------------------------------------
def _render_format_pills() -> None:
    for fmt in ("CSV", "Excel (.xlsx)", "JSON", "JSONL"):
        st.markdown(f'<span class="dw-format-pill">{fmt}</span>', unsafe_allow_html=True)


def tab_upload() -> None:
    st.subheader("📤 Upload files")
    left, right = st.columns([2, 1])
    with left:
        st.markdown("Drop files here to start a new pipeline run.")
        _render_format_pills()
    with right:
        if st.session_state.batch_id:
            st.info(f"Active batch:\n`{st.session_state.batch_id}`")
        else:
            st.success("A new batch will be created on upload.")

    uploaded = st.file_uploader(
        "Choose one or more files",
        type=["csv", "xlsx", "xls", "xlsm", "json", "jsonl", "ndjson"],
        accept_multiple_files=True,
        help=f"Max {settings.max_upload_mb} MB per file",
    )

    if uploaded:
        total = sum(len(f.getvalue()) for f in uploaded)
        names = ", ".join(f.name for f in uploaded[:5])
        if len(uploaded) > 5:
            names += f" (+{len(uploaded) - 5} more)"
        st.caption(f"**{len(uploaded)}** file(s) · **{_fmt_bytes(total)}** — {names}")

    use_existing = st.checkbox(
        "Append to current batch",
        value=bool(st.session_state.batch_id),
        disabled=not st.session_state.batch_id,
    )

    if st.button("🚀 Upload & start", type="primary", disabled=not uploaded, use_container_width=False):
        files = [(f.name, f.getvalue()) for f in uploaded]
        batch_id = st.session_state.batch_id if use_existing else None
        try:
            with upload_context() as svc:
                resp = svc.upload_batch_sync(
                    files, batch_id=batch_id, created_by="streamlit",
                )
            _set_active_batch(resp.batch_id)
            _save_progress_step(
                resp.batch_id, "upload", "done",
                message=f"{resp.total_files} file(s) uploaded",
            )
            for step in ("bronze", "silver", "relationships", "gold"):
                _save_progress_step(resp.batch_id, step, "pending", message="Not started")
            st.toast(f"Uploaded {resp.total_files} file(s)", icon="✅")
            st.success(f"Batch **`{resp.batch_id}`** is ready — go to **Pipeline** to run Bronze.")
            df = pd.DataFrame([f.model_dump() for f in resp.files])
            with st.expander("Uploaded files", expanded=True):
                show = df[["original_file_name", "file_type", "file_size"]].copy()
                show.columns = ["File", "Type", "Size"]
                show["Size"] = show["Size"].apply(_fmt_bytes)
                st.dataframe(show.head(20), use_container_width=True, hide_index=True)
            st.rerun()
        except Exception as exc:
            _show_error(exc)

    if st.session_state.batch_id:
        st.divider()
        try:
            status = _load_status(st.session_state.batch_id)
            _render_task_tracker(st.session_state.batch_id, status)
            uploaded = _list_uploaded_files(st.session_state.batch_id)
            if uploaded:
                with st.expander("Preview uploaded data", expanded=True):
                    names = [
                        f.original_file_name if hasattr(f, "original_file_name")
                        else f.get("original_file_name", "")
                        for f in uploaded
                    ]
                    pick = st.selectbox("File", names, key="upload_preview_pick")
                    for f in uploaded:
                        fname = f.original_file_name if hasattr(f, "original_file_name") else f.get("original_file_name")
                        if fname == pick:
                            path = f.stored_file_path if hasattr(f, "stored_file_path") else f.get("stored_file_path")
                            _preview_raw_file(path, max_rows=30)
                            break
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Pipeline task tracker + data explorer
# ---------------------------------------------------------------------------
PIPELINE_TASKS = (
    ("upload", "Upload files", "📤"),
    ("bronze", "Bronze ingest", "🥉"),
    ("silver", "Silver clean", "🥈"),
    ("relationships", "Detect relationships", "🔗"),
    ("gold", "Build Gold", "🥇"),
)

TASK_STATE_META = {
    "pending": ("⏳", "Pending", "pending"),
    "running": ("🔄", "Running", "running"),
    "done": ("✅", "Done", "done"),
    "failed": ("❌", "Failed", "failed"),
}


def _progress_steps_from_store(batch_id: str) -> dict[str, dict]:
    if use_file_storage():
        from app.services.file_store import FileBatchStore
        return FileBatchStore(batch_id).load_pipeline_progress()
    return st.session_state.get("pipeline_progress", {}).get(batch_id, {}).get("steps", {})


def _save_progress_step(
    batch_id: str, step: str, state: str, *, message: str = "", detail: str = "",
) -> None:
    if use_file_storage():
        from app.services.file_store import FileBatchStore
        FileBatchStore(batch_id).save_pipeline_step(step, state, message=message, detail=detail)
    bucket = st.session_state.setdefault("pipeline_progress", {})
    batch_bucket = bucket.setdefault(batch_id, {"steps": {}})
    batch_bucket["steps"][step] = {
        "state": state, "message": message, "detail": detail,
    }


def _infer_task_state(step: str, status, saved: dict[str, dict], running_step: str | None) -> dict:
    if running_step == step:
        return {"state": "running", "message": "In progress…", "detail": ""}
    if step in saved:
        return saved[step]
    if step == "upload":
        raw_n = len(_list_uploaded_files(status.batch_id))
        if raw_n:
            return {"state": "done", "message": f"{raw_n} file(s)", "detail": ""}
        return {"state": "pending", "message": "Waiting for upload", "detail": ""}
    if step == "bronze":
        if status.bronze_tables:
            return {"state": "done", "message": f"{len(status.bronze_tables)} table(s)", "detail": ", ".join(status.bronze_tables[:3])}
        return {"state": "pending", "message": "Not started", "detail": ""}
    if step == "silver":
        if status.silver_tables:
            return {"state": "done", "message": f"{len(status.silver_tables)} table(s)", "detail": ", ".join(status.silver_tables[:3])}
        return {"state": "pending", "message": "Not started", "detail": ""}
    if step == "relationships":
        if status.suggestion_count:
            return {"state": "done", "message": f"{status.suggestion_count} suggestion(s)", "detail": f"{status.approved_count} approved"}
        if status.silver_tables and len(status.silver_tables) < 2:
            return {"state": "done", "message": "Skipped (single table)", "detail": ""}
        return {"state": "pending", "message": "Not started", "detail": ""}
    if step == "gold":
        if status.gold_tables:
            return {"state": "done", "message": f"{len(status.gold_tables)} table(s)", "detail": ", ".join(status.gold_tables[:3])}
        return {"state": "pending", "message": "Not started", "detail": ""}
    return {"state": "pending", "message": "", "detail": ""}


def _list_uploaded_files(batch_id: str) -> list:
    if use_file_storage():
        from app.services.file_store import FileBatchStore
        return FileBatchStore(batch_id).list_files()
    from app.core.database import session_scope
    from app.models import UploadedFile
    with session_scope() as session:
        return session.query(UploadedFile).filter(UploadedFile.batch_id == batch_id).all()


def _render_task_tracker(batch_id: str, status, *, running_step: str | None = None) -> None:
    saved = _progress_steps_from_store(batch_id)
    rows = []
    for key, label, icon in PIPELINE_TASKS:
        info = _infer_task_state(key, status, saved, running_step)
        state = info.get("state", "pending")
        sym, state_label, css = TASK_STATE_META.get(state, ("⏳", state, "pending"))
        msg = info.get("message") or ""
        detail = info.get("detail") or ""
        rows.append({
            "": sym,
            "Step": f"{icon} {label}",
            "Status": state_label,
            "Summary": msg,
            "Detail": detail,
        })
    st.markdown("#### Task progress")
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    done_n = sum(1 for r in rows if r["Status"] == "Done")
    st.progress(done_n / len(PIPELINE_TASKS), text=f"{done_n} / {len(PIPELINE_TASKS)} steps complete")


def _run_full_pipeline_tracked(batch_id: str) -> None:
    steps = [
        ("bronze", "Bronze ingest", lambda svc: svc.run_bronze(batch_id)),
        ("silver", "Silver clean", lambda svc: svc.run_silver(batch_id)),
        ("relationships", "Detect relationships", lambda svc: svc.run_relationships(batch_id)),
    ]
    bar = st.progress(0, text="Starting pipeline…")
    try:
        with st.status("Running full pipeline…", expanded=True) as box:
            for i, (key, label, fn) in enumerate(steps):
                st.session_state.pipeline_running_step = key
                _save_progress_step(batch_id, key, "running", message=label)
                bar.progress(i / len(steps), text=label)
                st.write(f"🔄 **{label}** …")
                with pipeline_context() as svc:
                    result = fn(svc)
                n = len(result)
                _save_progress_step(batch_id, key, "done", message=f"{n} item(s)")
                st.write(f"✅ {label} — {n} finished")
            st.session_state.pipeline_running_step = None
            _save_progress_step(batch_id, "gold", "pending", message="Run Gold after approving relationships")
            bar.progress(1.0, text="Bronze → Silver → Relationships complete")
            box.update(label="Pipeline stages complete (Gold pending approval)", state="complete")
        _invalidate_batch_cache()
        st.success("Full run finished. Review relationships, then build Gold. Browse data below.")
    except Exception as exc:
        key = st.session_state.get("pipeline_running_step")
        if key:
            _save_progress_step(batch_id, key, "failed", message=str(exc)[:200])
        st.session_state.pipeline_running_step = None
        raise


def _preview_raw_file(stored_path: str, *, max_rows: int = 50) -> None:
    from app.services.file_reader_service import read_file
    try:
        result = read_file(stored_path)
        if not result.frames:
            st.caption("No data in file.")
            return
        for fi in result.frames:
            if len(result.frames) > 1:
                st.caption(f"Sheet / dataset: **{fi.name}**")
            df = fi.frame.head(max_rows).to_pandas()
            _safe_dataframe(df, max_rows=max_rows)
    except Exception as exc:
        st.warning(f"Could not preview file: {exc}")


def _render_data_explorer(batch_id: str, status) -> None:
    st.markdown("#### View data")
    preview_rows = st.slider("Preview rows", 10, 500, 50, key=f"preview_rows_{batch_id}")

    t_raw, t_bronze, t_silver, t_gold = st.tabs(["📤 Raw uploads", "🥉 Bronze", "🥈 Silver", "🥇 Gold"])

    with t_raw:
        uploaded = _list_uploaded_files(batch_id)
        if not uploaded:
            st.info("No uploaded files yet.")
        else:
            names = [
                f.original_file_name if hasattr(f, "original_file_name") else f["original_file_name"]
                for f in uploaded
            ]
            pick = st.selectbox("Select file", names, key=f"raw_pick_{batch_id}")
            for f in uploaded:
                fname = f.original_file_name if hasattr(f, "original_file_name") else f.get("original_file_name")
                if fname == pick:
                    path = f.stored_file_path if hasattr(f, "stored_file_path") else f.get("stored_file_path")
                    st.caption(f"`{path}`")
                    _preview_raw_file(path, max_rows=preview_rows)
                    break

    for tab, layer, tables in (
        (t_bronze, "bronze", status.bronze_tables),
        (t_silver, "silver", status.silver_tables),
        (t_gold, "gold", status.gold_tables),
    ):
        with tab:
            if not tables:
                st.info(f"No {layer} tables yet — run the pipeline step above.")
            else:
                pick = st.selectbox(
                    f"Select {layer} table",
                    tables,
                    key=f"{layer}_pick_{batch_id}",
                )
                if pick:
                    _preview_table_data(batch_id, pick, layer, max_rows=preview_rows)


def _preview_table_data(
    batch_id: str, table_name: str, layer: str, *, max_rows: int = 25,
) -> None:
    if not use_file_storage():
        st.caption("Table preview requires file mode (parquet on disk).")
        return
    try:
        from app.services.file_store import FileBatchStore
        store = FileBatchStore(batch_id)
        if layer == "bronze":
            df = store.read_bronze_parquet(table_name)
        elif layer == "silver":
            df = store.read_silver_parquet(table_name)
        else:
            df = store.read_gold_parquet(table_name)
        if df.is_empty():
            st.caption("Empty table.")
            return
        data_cols = [c for c in df.columns if not str(c).startswith("_")]
        preview = df.select(data_cols) if data_cols else df
        st.caption(f"{preview.height} rows × {len(preview.columns)} columns")
        _safe_dataframe(preview.to_pandas(), max_rows=max_rows)
    except Exception as exc:
        st.caption(f"Preview unavailable: {exc}")


def _run_single_stage(batch_id: str, step: str, label: str, fn) -> None:
    st.session_state.pipeline_running_step = step
    _save_progress_step(batch_id, step, "running", message=label)
    try:
        with pipeline_context() as svc:
            result = fn(svc)
        _save_progress_step(batch_id, step, "done", message=f"{len(result)} item(s)")
        st.toast(f"{label} complete", icon="✅")
    except Exception as exc:
        _save_progress_step(batch_id, step, "failed", message=str(exc)[:200])
        raise
    finally:
        st.session_state.pipeline_running_step = None


def tab_pipeline(batch_id: str | None) -> None:
    st.subheader("⚙️ Pipeline")
    if not batch_id:
        st.markdown(
            '<div class="dw-hero"><h2>Get started</h2>'
            "<p>Upload files on the <strong>Upload</strong> tab, then return here to run the pipeline.</p></div>",
            unsafe_allow_html=True,
        )
        st.info("👈 Select a batch in the sidebar after uploading.")
        return

    try:
        status = _load_status(batch_id)
    except Exception as exc:
        st.warning(f"Could not load status: {exc}")
        return

    running = st.session_state.get("pipeline_running_step")
    _render_task_tracker(batch_id, status, running_step=running)
    _render_stepper(status.current_stage)
    _render_next_action(status.current_stage)

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        if st.button("▶ Full run", use_container_width=True, help="Bronze → Silver → Relationships"):
            try:
                _run_full_pipeline_tracked(batch_id)
                st.rerun()
            except Exception as exc:
                _show_error(exc)
    with c2:
        if st.button("🥉 Bronze", use_container_width=True):
            try:
                _run_single_stage(batch_id, "bronze", "Bronze", lambda svc: svc.run_bronze(batch_id))
                st.rerun()
            except Exception as exc:
                _show_error(exc)
    with c3:
        if st.button("🥈 Silver", use_container_width=True):
            try:
                _run_single_stage(batch_id, "silver", "Silver", lambda svc: svc.run_silver(batch_id))
                st.rerun()
            except Exception as exc:
                _show_error(exc)
    with c4:
        if st.button("🔗 Relate", use_container_width=True):
            try:
                _run_single_stage(
                    batch_id, "relationships", "Relationships",
                    lambda svc: svc.run_relationships(batch_id),
                )
                st.rerun()
            except Exception as exc:
                _show_error(exc)
    with c5:
        if st.button("🥇 Gold", type="primary", use_container_width=True):
            try:
                _run_single_stage(batch_id, "gold", "Gold", lambda svc: svc.run_gold(batch_id))
                st.rerun()
            except Exception as exc:
                _show_error(exc)

    st.divider()
    status = _load_status(batch_id)
    _render_data_explorer(batch_id, status)


# ---------------------------------------------------------------------------
# Tab: Relationships
# ---------------------------------------------------------------------------
def tab_relationships(batch_id: str | None) -> None:
    st.subheader("🔗 Relationship approval")
    st.caption(
        "Approve links before Gold when you have multiple Silver tables. "
        "High confidence + value overlap = safer joins."
    )
    if not batch_id:
        st.info("Select a batch in the sidebar.")
        return

    try:
        if use_file_storage():
            svc = get_file_pipeline()
            suggestions = svc.list_suggestions(batch_id)
            approved = svc.list_approved(batch_id)
        else:
            from app.core.database import session_scope
            from app.services.relationship_approval_service import RelationshipApprovalService
            with session_scope() as session:
                rel_svc = RelationshipApprovalService(session)
                suggestions = rel_svc.list_suggestions(batch_id)
                approved = rel_svc.list_approved(batch_id)
    except Exception as exc:
        _show_error(exc)
        return

    m1, m2, m3 = st.columns(3)
    m1.metric("Approved", len(approved))
    m2.metric("Pending", sum(1 for s in suggestions if s.status == "suggested"))
    m3.metric("Total found", len(suggestions))

    if approved:
        st.subheader("✅ Approved relationships")
        st.dataframe(
            pd.DataFrame([
                {
                    "source": f"{a.source_table}.{a.source_column}",
                    "target": f"{a.target_table}.{a.target_column}",
                    "type": a.relation_type,
                    "note": a.note or "",
                }
                for a in approved
            ]),
            use_container_width=True,
        )

    if not suggestions:
        st.info("No suggestions yet. Run **🔗 Relate** on the Pipeline tab.")
        return

    filter_status = st.radio(
        "Show",
        ["All", "Suggested", "Approved", "Rejected"],
        horizontal=True,
        label_visibility="collapsed",
    )
    shown = suggestions
    if filter_status != "All":
        key = filter_status.lower()
        shown = [s for s in suggestions if s.status == key]

    st.markdown(f"#### Suggestions ({len(shown)})")
    for sug in shown:
        conf = sug.confidence_score or 0
        conf_pct = f"{conf * 100:.0f}%"
        risk = sug.risk_level or "none"
        status_icon = {"suggested": "🟡", "approved": "🟢", "rejected": "🔴"}.get(sug.status, "⚪")
        with st.expander(
            f"{status_icon} {sug.source_table}.{sug.source_column} → "
            f"{sug.target_table}.{sug.target_column} · {conf_pct} · {risk}",
            expanded=sug.status == "suggested",
        ):
            st.progress(conf, text=f"Confidence {conf_pct}")
            c1, c2, c3 = st.columns(3)
            c1.metric("Name match", f"{(sug.column_name_similarity_score or 0) * 100:.0f}%")
            c2.metric("Value overlap", f"{(sug.value_overlap_score or 0) * 100:.0f}%")
            c3.metric("Matching values", sug.matching_values_count or 0)
            st.caption(f"Type: **{sug.suggested_relation_type}**")

            if sug.risk_reason:
                st.warning(sug.risk_reason)
            if sug.recommendation:
                st.caption(sug.recommendation)

            if sug.status == "suggested":
                note = st.text_input("Note", key=f"note_{sug.id}")
                b1, b2 = st.columns(2)
                with b1:
                    if st.button("✅ Approve", key=f"approve_{sug.id}", type="primary"):
                        try:
                            if use_file_storage():
                                get_file_pipeline().approve_relationship(
                                    batch_id, sug.id, decided_by="streamlit", note=note or None,
                                )
                            else:
                                from app.core.database import session_scope
                                from app.services.relationship_approval_service import RelationshipApprovalService
                                with session_scope() as session:
                                    RelationshipApprovalService(session).approve(
                                        batch_id, sug.id, decided_by="streamlit", note=note or None,
                                    )
                            _invalidate_batch_cache()
                            st.rerun()
                        except Exception as exc:
                            _show_error(exc)
                with b2:
                    if st.button("❌ Reject", key=f"reject_{sug.id}"):
                        try:
                            if use_file_storage():
                                get_file_pipeline().reject_relationship(
                                    batch_id, sug.id, decided_by="streamlit", note=note or None,
                                )
                            else:
                                from app.core.database import session_scope
                                from app.services.relationship_approval_service import RelationshipApprovalService
                                with session_scope() as session:
                                    RelationshipApprovalService(session).reject(
                                        batch_id, sug.id, decided_by="streamlit", note=note or None,
                                    )
                            st.rerun()
                        except Exception as exc:
                            _show_error(exc)


# ---------------------------------------------------------------------------
# Tab: Reports
# ---------------------------------------------------------------------------
def tab_reports(batch_id: str | None) -> None:
    st.subheader("📊 Reports")
    if not batch_id:
        st.info("Select a batch in the sidebar.")
        return

    report_tab, dict_tab, lineage_tab = st.tabs(
        ["🚨 Quality", "📖 Dictionary", "🔀 Lineage"]
    )

    with report_tab:
        try:
            if use_file_storage():
                issues = get_file_pipeline().list_quality_issues(batch_id)
            else:
                from app.core.database import session_scope
                from app.models import QualityIssue
                with session_scope() as session:
                    issues = (
                        session.query(QualityIssue)
                        .filter(QualityIssue.batch_id == batch_id)
                        .order_by(QualityIssue.severity, QualityIssue.table_name)
                        .all()
                    )
        except Exception as exc:
            _show_error(exc)
            return

        if not issues:
            st.success("No quality issues — data looks clean for this batch.")
        else:
            by_sev: dict[str, int] = {}
            for i in issues:
                sev = i["severity"] if isinstance(i, dict) else i.severity
                by_sev[sev] = by_sev.get(sev, 0) + 1
            sev_order = ["Critical", "High", "Medium", "Low", "Info"]
            ordered = [(s, by_sev[s]) for s in sev_order if s in by_sev]
            ordered += [(s, c) for s, c in by_sev.items() if s not in sev_order]
            cols = st.columns(min(5, max(1, len(ordered))))
            for col, (sev, cnt) in zip(cols, ordered):
                col.metric(sev, cnt)

            sev_filter = st.multiselect(
                "Filter by severity",
                options=list(by_sev.keys()),
                default=list(by_sev.keys()),
            )

            rows = []
            for i in issues:
                if isinstance(i, dict):
                    samples = i.get("sample_values") or []
                    rows.append({
                        "severity": i.get("severity"),
                        "layer": i.get("layer"),
                        "table": i.get("table_name"),
                        "column": i.get("column_name") or "—",
                        "type": i.get("issue_type"),
                        "description": i.get("issue_description"),
                        "affected %": round(i.get("affected_rows_percentage") or 0, 1),
                        "auto_fix": i.get("auto_fix_available"),
                        "samples": ", ".join(str(s)[:40] for s in samples[:3]),
                    })
                else:
                    samples = []
                    try:
                        samples = json.loads(i.sample_values_json or "[]")
                    except json.JSONDecodeError:
                        pass
                    rows.append({
                        "severity": i.severity,
                        "layer": i.layer,
                        "table": i.table_name,
                        "column": i.column_name or "—",
                        "type": i.issue_type,
                        "description": i.issue_description,
                        "affected %": round(i.affected_rows_percentage or 0, 1),
                        "auto_fix": i.auto_fix_available,
                        "samples": ", ".join(str(s)[:40] for s in samples[:3]),
                    })
            df_issues = pd.DataFrame(rows)
            if sev_filter and "severity" in df_issues.columns:
                df_issues = df_issues[df_issues["severity"].isin(sev_filter)]
            st.dataframe(df_issues, use_container_width=True, hide_index=True)

    with dict_tab:
        try:
            if use_file_storage():
                cols = get_file_pipeline().list_column_profiles(batch_id)
            else:
                from app.core.database import session_scope
                from app.models import ColumnProfile
                with session_scope() as session:
                    orm_cols = (
                        session.query(ColumnProfile)
                        .filter(ColumnProfile.batch_id == batch_id)
                        .order_by(ColumnProfile.table_name, ColumnProfile.column_name)
                        .all()
                    )
                    cols = orm_cols
        except Exception as exc:
            _show_error(exc)
            return

        if not cols:
            st.info("No column profiles yet. Run Bronze on the Pipeline tab.")
        else:
            search = st.text_input("Search columns", placeholder="Table or column name…")
            if isinstance(cols[0], dict):
                dict_df = pd.DataFrame([
                    {
                        "layer": c["layer"],
                        "table": c["table_name"],
                        "column": c["column_name"],
                        "original": c.get("original_column_name") or "",
                        "physical": c.get("physical_type"),
                        "semantic": c.get("semantic_type"),
                        "null %": round(c.get("null_percentage") or 0, 1),
                        "unique %": round((c.get("uniqueness_ratio") or 0) * 100, 1),
                        "arabic %": round(c.get("arabic_text_percentage") or 0, 1),
                    }
                    for c in cols
                ])
                if search:
                    mask = dict_df.apply(
                        lambda r: search.lower() in str(r["table"]).lower()
                        or search.lower() in str(r["column"]).lower(),
                        axis=1,
                    )
                    dict_df = dict_df[mask]
                _safe_dataframe(dict_df, max_rows=300)
            else:
                dict_df = pd.DataFrame([
                    {
                        "layer": c.layer,
                        "table": c.table_name,
                        "column": c.column_name,
                        "original": c.original_column_name or "",
                        "physical": c.physical_type,
                        "semantic": c.semantic_type,
                        "null %": round(c.null_percentage or 0, 1),
                        "unique %": round((c.uniqueness_ratio or 0) * 100, 1),
                        "arabic %": round(c.arabic_text_percentage or 0, 1),
                    }
                    for c in cols
                ])
                if search:
                    mask = dict_df.apply(
                        lambda r: search.lower() in str(r["table"]).lower()
                        or search.lower() in str(r["column"]).lower(),
                        axis=1,
                    )
                    dict_df = dict_df[mask]
                _safe_dataframe(dict_df, max_rows=300)

    with lineage_tab:
        try:
            if use_file_storage():
                from app.services.file_store import FileBatchStore
                store = FileBatchStore(batch_id)
                edges = []
                for b in store.list_bronze_tables():
                    edges.append({"from": b.source_file_name, "to": b.table_name, "layer": "raw→bronze"})
                for s in store.list_silver_tables():
                    edges.append({"from": f"bronze#{s.bronze_table_id}", "to": s.table_name, "layer": "bronze→silver"})
                for g in store.list_gold_tables():
                    for src in (g.source_silver_tables or "").split(","):
                        src = src.strip()
                        if src:
                            edges.append({"from": src, "to": g.table_name, "layer": "silver→gold"})
            else:
                from app.core.database import session_scope
                from app.models import BronzeTable, GoldTable, SilverTable
                with session_scope() as session:
                    edges = []
                    for b in session.query(BronzeTable).filter(BronzeTable.batch_id == batch_id):
                        edges.append({"from": b.source_file_name, "to": b.table_name, "layer": "raw→bronze"})
                    for s in session.query(SilverTable).filter(SilverTable.batch_id == batch_id):
                        edges.append({"from": f"bronze#{s.bronze_table_id}", "to": s.table_name, "layer": "bronze→silver"})
                    for g in session.query(GoldTable).filter(GoldTable.batch_id == batch_id):
                        for src in (g.source_silver_tables or "").split(","):
                            src = src.strip()
                            if src:
                                edges.append({"from": src, "to": g.table_name, "layer": "silver→gold"})
        except Exception as exc:
            _show_error(exc)
            return

        if edges:
            st.dataframe(pd.DataFrame(edges), use_container_width=True)
        else:
            st.info("No lineage data yet.")


# ---------------------------------------------------------------------------
# Tab: Exports
# ---------------------------------------------------------------------------
def tab_exports(batch_id: str | None) -> None:
    st.subheader("📦 Exports")
    if use_file_storage():
        st.caption("Tables are **Parquet** on disk. Optional **CSV copies** — downloads keep original extensions.")
    else:
        st.caption("Power BI, ZakaaDash, SQL scripts, and cleaned file bundles.")
    if not batch_id:
        st.info("Select a batch in the sidebar.")
        return

    col1, col2, col3, col4 = st.columns(4)
    export_dir = settings.batch_exports_dir(batch_id)

    if col1.button("Power BI package"):
        if use_file_storage():
            st.info("Power BI export requires MySQL mode. Use **Export CSV bundle** below.")
        else:
            with st.spinner("Building Power BI export…"):
                try:
                    from app.core.database import session_scope
                    from app.services.powerbi_export_service import PowerBIExportService
                    with session_scope() as session:
                        path = PowerBIExportService(session).export(batch_id)
                    st.success(f"Saved to `{path}`")
                    _list_export_files(path)
                except Exception as exc:
                    _show_error(exc)

    if col2.button("ZakaaDash package"):
        if use_file_storage():
            st.info("ZakaaDash export requires MySQL mode. Use **Export CSV bundle** below.")
        else:
            with st.spinner("Building ZakaaDash export…"):
                try:
                    from app.core.database import session_scope
                    from app.services.zakaadash_export_service import ZakaaDashExportService
                    with session_scope() as session:
                        path = ZakaaDashExportService(session).export(batch_id)
                    st.success(f"Saved to `{path}`")
                    _list_export_files(path)
                except Exception as exc:
                    _show_error(exc)

    if col3.button("SQL scripts"):
        if use_file_storage():
            st.info("SQL generation is available after switching to MySQL mode.")
        else:
            with st.spinner("Generating SQL…"):
                try:
                    from app.core.database import session_scope
                    from app.services.sql_generator_service import SQLGeneratorService
                    with session_scope() as session:
                        files = SQLGeneratorService(session).generate_all(batch_id)
                    st.success("SQL generated.")
                    for name, p in files.items():
                        st.text(f"{name}: {p}")
                except Exception as exc:
                    _show_error(exc)

    if col4.button("📥 CSV copies", help="Optional CSV copies (parquet remains primary)"):
        with st.spinner("Writing CSV copies…"):
            try:
                if use_file_storage():
                    artifacts = get_file_pipeline().export_csv_bundle(batch_id)
                    st.success(f"CSV copies ready — {len(artifacts)} file(s). See **Files** tab.")
                    st.rerun()
                else:
                    from app.core.database import session_scope
                    from app.services.export_service import ExportService
                    with session_scope() as session:
                        artifacts = ExportService(session).export_all(batch_id)
                    st.success(f"Export complete — {len(artifacts)} artifact(s).")
                    st.json(artifacts)
            except Exception as exc:
                _show_error(exc)

    st.divider()
    st.markdown("#### Quick downloads")
    _render_file_browser(batch_id, cleaned_only=True, ui_scope="exports")


def _download_payload(info) -> tuple[bytes, str, str]:
    """Return (bytes, filename, mime) — same extension as on disk (.parquet, .xlsx, …)."""
    from app.utils.batch_file_browser import download_payload

    return download_payload(info)


def _render_file_browser(batch_id: str, *, cleaned_only: bool = False, ui_scope: str = "files") -> None:
    from app.utils.batch_file_browser import (
        build_batch_zip,
        cleaned_file_infos,
        list_batch_files,
    )

    all_files = cleaned_file_infos(batch_id) if cleaned_only else list_batch_files(batch_id)
    if not all_files:
        st.info("No files yet. Upload, run the pipeline, then use **Export Parquet bundle**.")
        return

    st.caption("Downloads keep the **original extension** (.parquet, .xlsx, .csv, …).")

    layer_filter = st.multiselect(
        "Filter by layer",
        options=sorted({f.layer for f in all_files}, key=lambda x: (
            ["raw", "bronze", "silver", "gold", "export", "sql", "metadata"].index(x)
            if x in ("raw", "bronze", "silver", "gold", "export", "sql", "metadata") else 99
        )),
        default=sorted({f.layer for f in all_files}),
        key=f"layer_filter_{ui_scope}_{batch_id}_{'cleaned' if cleaned_only else 'all'}",
        format_func=lambda x: {
            "raw": "📤 Raw uploads",
            "bronze": "🥉 Bronze (.parquet)",
            "silver": "🥈 Silver (.parquet)",
            "gold": "🥇 Gold (.parquet)",
            "export": "📥 Exports",
            "sql": "📝 SQL",
            "metadata": "📋 Metadata",
        }.get(x, x),
    )
    shown = [f for f in all_files if f.layer in layer_filter] if layer_filter else all_files

    total_bytes = sum(f.size_bytes for f in shown)
    st.caption(f"**{len(shown)}** file(s) · **{_fmt_bytes(total_bytes)}** total")

    from app.utils.batch_file_browser import build_batch_zip_as_csv

    zip_layers = set(layer_filter) if layer_filter else None
    layers_key = "all" if not zip_layers else "_".join(sorted(zip_layers))
    scope_key = "cleaned" if cleaned_only else "all"
    z1, z2, z3 = st.columns(3)
    with z1:
        st.download_button(
            "📦 ZIP (original formats)",
            data=build_batch_zip(batch_id, layers=zip_layers),
            file_name=f"{batch_id}_files.zip",
            mime="application/zip",
            key=f"zip_orig_{ui_scope}_{batch_id}_{scope_key}_{layers_key}",
            use_container_width=True,
            help="Parquet stays .parquet, Excel stays .xlsx, etc.",
        )
    with z2:
        st.download_button(
            "📦 ZIP (Parquet layers)",
            data=build_batch_zip(batch_id, layers={"bronze", "silver", "gold"}),
            file_name=f"{batch_id}_parquet.zip",
            mime="application/zip",
            key=f"zip_parquet_{ui_scope}_{batch_id}_{scope_key}",
            use_container_width=True,
        )
    with z3:
        st.download_button(
            "📦 ZIP (as CSV)",
            data=build_batch_zip_as_csv(batch_id, layers=zip_layers),
            file_name=f"{batch_id}_csv.zip",
            mime="application/zip",
            key=f"zip_csv_{ui_scope}_{batch_id}_{scope_key}_{layers_key}",
            use_container_width=True,
            help="Converts .parquet to .csv inside the ZIP only",
        )

    rows = [
        {
            "Layer": f.layer,
            "File": f.display_name,
            "Size": _fmt_bytes(f.size_bytes),
            "Type": f.extension or "—",
        }
        for f in shown
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.markdown("#### Download individual files")
    layer_labels = {
        "raw": "📤 Raw uploads",
        "bronze": "🥉 Bronze (.parquet)",
        "silver": "🥈 Silver (.parquet)",
        "gold": "🥇 Gold (.parquet)",
        "export": "📥 Exports",
        "sql": "📝 SQL scripts",
        "metadata": "📋 Metadata",
    }
    for layer in sorted({f.layer for f in shown}, key=lambda x: (
        ["raw", "bronze", "silver", "gold", "export", "sql", "metadata"].index(x)
        if x in ("raw", "bronze", "silver", "gold", "export", "sql", "metadata") else 99
    )):
        layer_files = [f for f in shown if f.layer == layer]
        with st.expander(f"{layer_labels.get(layer, layer)} ({len(layer_files)})", expanded=layer in ("silver", "gold")):
            for info in layer_files:
                c1, c2, c3 = st.columns([4, 1, 1])
                c1.markdown(f"`{info.display_name}`")
                c2.caption(_fmt_bytes(info.size_bytes))
                data, fname, mime = _download_payload(info)
                c3.download_button(
                    "⬇️",
                    data=data,
                    file_name=fname,
                    mime=mime,
                    key=f"dl_{ui_scope}_{scope_key}_{batch_id}_{layer}_{info.relative_path}",
                    help=f"Download {fname}",
                )


def tab_files(batch_id: str | None) -> None:
    st.subheader("📁 All files & downloads")
    st.caption(
        "Pipeline tables are stored as **Parquet** (.parquet). "
        "Uploads keep their type (.xlsx, .csv, …). Downloads use the **same extension** as on disk."
    )

    if not batch_id:
        st.info("Select a batch in the sidebar.")
        return

    a1, a2, a3, a4 = st.columns(4)
    with a1:
        if st.button("🔄 Refresh", use_container_width=True, key="files_refresh"):
            st.rerun()
    with a2:
        if st.button("📦 Parquet bundle", type="primary", use_container_width=True, key="files_parquet_bundle"):
            with st.spinner("Copying parquet files…"):
                try:
                    if use_file_storage():
                        n = len(get_file_pipeline().export_parquet_bundle(batch_id))
                    else:
                        n = 0
                        st.warning("Parquet bundle is available in file mode.")
                    if n:
                        st.toast(f"{n} parquet file(s) in exports/parquet/", icon="✅")
                        st.rerun()
                except Exception as exc:
                    _show_error(exc)
    with a3:
        if st.button("📄 CSV copies", use_container_width=True, key="files_csv_copies"):
            with st.spinner("Writing CSV copies…"):
                try:
                    if use_file_storage():
                        n = len(get_file_pipeline().export_csv_bundle(batch_id))
                    else:
                        from app.core.database import session_scope
                        from app.services.export_service import ExportService
                        with session_scope() as session:
                            n = len(ExportService(session).export_all(batch_id))
                    st.toast(f"{n} CSV file(s)", icon="✅")
                    st.rerun()
                except Exception as exc:
                    _show_error(exc)
    with a4:
        st.caption("Formats")
        st.markdown(
            '<span class="dw-format-pill">.parquet</span>'
            '<span class="dw-format-pill">.csv</span>'
            '<span class="dw-format-pill">.xlsx</span>',
            unsafe_allow_html=True,
        )

    tab_all, tab_parquet, tab_clean = st.tabs([
        "All files", "Parquet only", "Pipeline outputs",
    ])
    with tab_all:
        _render_file_browser(batch_id, cleaned_only=False, ui_scope="files_all")
    with tab_parquet:
        from app.utils.batch_file_browser import parquet_file_infos

        files = parquet_file_infos(batch_id)
        if not files:
            st.info("No .parquet files yet. Run Bronze/Silver on the Pipeline tab.")
        else:
            st.caption(f"{len(files)} parquet file(s)")
            for info in files:
                c1, c2, c3 = st.columns([4, 1, 1])
                c1.markdown(f"`{info.layer}/{info.download_filename}`")
                c2.caption(_fmt_bytes(info.size_bytes))
                data, fname, mime = _download_payload(info)
                c3.download_button("⬇️ .parquet", data=data, file_name=fname, mime=mime,
                                     key=f"pq_{batch_id}_{info.layer}_{info.relative_path}")
    with tab_clean:
        _render_file_browser(batch_id, cleaned_only=True, ui_scope="files_cleaned")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def _tab_labels(batch_id: str | None) -> list[str]:
    base = ["📤 Upload", "⚙️ Pipeline", "🔗 Relationships", "📊 Reports", "📁 Files", "📦 Exports"]
    if not batch_id:
        return base
    try:
        s = _load_status(batch_id)
        base[1] = f"⚙️ Pipeline ({STAGE_LABELS.get(_normalize_stage(s.current_stage), '?')})"
        if s.suggestion_count:
            base[2] = f"🔗 Relationships ({s.suggestion_count})"
        if s.quality_issue_count:
            base[3] = f"📊 Reports ({s.quality_issue_count})"
        from app.utils.batch_file_browser import list_batch_files
        nfiles = len(list_batch_files(batch_id))
        if nfiles:
            base[4] = f"📁 Files ({nfiles})"
    except Exception:
        pass
    return base


def main() -> None:
    _init()
    _inject_custom_css()
    batch_id = _sidebar()

    h1, h2 = st.columns([3, 1])
    with h1:
        mode = "File mode" if use_file_storage() else "MySQL mode"
        st.markdown(
            f'<div class="dw-hero"><h2>Data Warehouse Builder</h2>'
            f"<p>Upload → profile → clean → relate → export · <strong>{mode}</strong></p></div>",
            unsafe_allow_html=True,
        )
    with h2:
        if batch_id:
            st.markdown("**Active batch**")
            st.code(batch_id, language=None)
        else:
            st.markdown("**No batch**")
            st.caption("Upload files to begin")

    tabs = st.tabs(_tab_labels(batch_id))
    t_upload, t_pipeline, t_rel, t_reports, t_files, t_exports = tabs

    with t_upload:
        tab_upload()
    with t_pipeline:
        tab_pipeline(batch_id)
    with t_rel:
        tab_relationships(batch_id)
    with t_reports:
        tab_reports(batch_id)
    with t_files:
        tab_files(batch_id)
    with t_exports:
        tab_exports(batch_id)


# Only run UI when Streamlit is executing this script (not on plain `import`).
from streamlit.runtime.scriptrunner import get_script_run_ctx

if get_script_run_ctx() is not None:
    main()
