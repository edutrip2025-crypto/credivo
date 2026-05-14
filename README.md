# Credivo Assessment Platform

Assessment-only web application for creating, issuing, taking, proctoring, and reviewing candidate assessments.

## Included

- Assessment builder and candidate assessment runtime
- Issued candidate access flow
- Proctoring event capture, review, retention cleanup, and training feedback
- AI proctoring model utilities and retraining scripts
- Coding environment and local execution route
- Excel tool simulator and Microsoft Graph Excel integration hooks
- Tax and accounting simulation UI source in the assessment tooling layer
- React assessment frontend with production build output

## Deliberately Excluded

- Classes, course marketplace, live-class, classroom, and stream-market routes/UI
- Local databases, logs, secrets, media captures, virtual environments, and node_modules

## Local Backend

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
set AUTH_MODE=dummy
set DATABASE_URL=sqlite:///./credivo.db
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000/assessment
```

## React Assessment Frontend

```bash
cd app/web_assessment_react
npm install
npm run build
```

The backend serves the built frontend from `app/web_assessment_react/dist`.

## Proctoring / AI Model

Core files:

- `app/api/routes/proctoring.py`
- `app/services/proctoring_ai.py`
- `app/services/proctor_training.py`
- `app/services/proctor_hard_negative.py`
- `app/services/proctor_retention.py`
- `ml/proctoring/`

Optional ML dependencies are listed in `requirements-ml.txt` and `ml/proctoring/requirements*.txt`.

## Tools

Core files:

- `app/api/routes/tools.py`
- `app/services/graph_excel.py`
- `app/web_assessment_react/src/features/tools/`

Microsoft Graph Excel variables are documented in `.env.example`.
