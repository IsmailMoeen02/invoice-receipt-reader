# Document Desk

Reads supplier invoices, receipts and credit notes (PDF, photo or scan), checks the arithmetic, and keeps a person in charge of anything doubtful. Includes a review dashboard, CSV/Excel export, a dummy supplier portal with a Playwright bot, an n8n workflow, and an evaluation. All suppliers, documents and amounts are dummy data.

**Demo videos and write-up:** [ismailmoeen.dev](https://ismailmoeen.dev/#work)

## Run
```
sudo apt install tesseract-ocr poppler-utils
pip install -r requirements.txt
DEMO_MODE=1 INBOUND_KEY=change-me uvicorn app.main:app --port 8000    # dashboard password in demo mode: demo
```
Without `ADMIN_PASSWORD` or `DEMO_MODE`, a random password is printed at start. An unset `INBOUND_KEY` means the inbound endpoints are closed, never open.

## Demo data, portal bot, tests
```
pip install -r requirements-dev.txt && playwright install chromium
python data/make_docs.py                      # dummy documents (data/docs is not committed, regenerate it; same seed, same files)
python portal/build_data.py                   # copies statement files into portal/files
python scripts/seed.py                        # fill the database
(cd portal && uvicorn app:app --port 8090)    # dummy supplier portal (buyer / portal-demo)
python portal/bot.py --key change-me          # collect, read and reconcile
pytest                                        # 69 tests, offline
python eval/run_eval.py dev|heldout [--show]  # measure against the answers
```
## Settings (environment)
`DB_PATH, FILES_DIR, ADMIN_PASSWORD, INBOUND_KEY, MAX_UPLOAD (10 MB), MAX_PAGES (20), GROQ_API_KEY` (optional; the model must quote every value from the document, otherwise it is dropped).

## Limits
Documents are generated, so cleaner than real paperwork. The Groq path is tested with a mock only. The portal is a dummy.
