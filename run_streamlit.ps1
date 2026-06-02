Set-Location $PSScriptRoot
if (Test-Path .\.venv\Scripts\Activate.ps1) { .\.venv\Scripts\Activate.ps1 }
streamlit run streamlit_app.py --server.port 8501 --server.address 127.0.0.1 --server.fileWatcherType none
