# Statera

Personal AI Career Assistant.

## Local development

Create a virtual environment, install dependencies and start the server:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Check the health endpoints:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/health/db
```
