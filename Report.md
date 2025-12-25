Code Review Report

Findings
- High: `TradeProposalResponse.created_at` is required, but `/api/analysis/status/{session_id}` builds the response with `created_at=proposal.get("created_at")`; if the proposal lacks `created_at`, Pydantic will raise a validation error and the status endpoint will 500. `backend/app/api/routes/analysis.py:208` + `backend/app/api/schemas/analysis.py:70`.
- Medium: `/api/analysis/status/{session_id}` returns `current_stage` as `str(state.get("current_stage"))`, which turns `None` into the literal string `"None"`; clients expecting `null` will mis-handle stage checks. `backend/app/api/routes/analysis.py:224`.
- Medium: Frontend `getSessionStatus` expects `analyses_count` and omits `analyses`, `trade_proposal`, and `reasoning_log`, but the backend response schema does not include `analyses_count` and does include the other fields. This is a response contract mismatch. `frontend/src/api/client.ts:102` + `backend/app/api/schemas/analysis.py:88`.
- Medium: Frontend `getSessionState` calls `/analysis/state/{sessionId}` but no such backend route exists, so this will 404 if invoked. `frontend/src/api/client.ts:118` + `backend/app/api/routes/analysis.py:162`.
- Low: Frontend `cancelSession` expects `{ success: boolean }` while the backend returns `{ message: string }`, so any caller checking `success` will break silently. `frontend/src/api/client.ts:130` + `backend/app/api/routes/analysis.py:260`.
