import streamlit as st

st.set_page_config(page_title="Import test", layout="wide")

st.title("Import test")

try:
    from app.core.config import settings
    st.success(f"Config OK: {settings.app_name}")
except Exception as exc:
    st.error(f"Config failed: {exc}")

try:
    from sqlalchemy import text
    from app.core.database import metadata_engine
    with metadata_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
    st.success("MySQL OK")
except Exception as exc:
    st.error(f"MySQL failed: {exc}")

try:
    from app.services.pipeline_service import PipelineService
    st.success("PipelineService OK")
except Exception as exc:
    st.error(f"Pipeline failed: {exc}")
