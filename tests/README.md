## Tests for Life Assistant

### Backend (FastAPI)
- **`tests/backend/test_main.py`**: Tests for `/auth/password`, `/maps/departure`, and `/ideas/audio` endpoints
- **`tests/backend/test_calendar.py`**: Tests for `/calendar/events` and `/calendar/classes`
- **`tests/backend/test_jobs.py`**: Tests for job creation, claiming, and execution flow

### Frontend (React)
- **`tests/frontend/Dashboard.test.js`**: Tests for dashboard rendering, authentication flow, and calendar integration
- **`tests/frontend/HomeAssistant.test.js`**: Tests for HA toggle and notification handling

### Additional suggestions:
- Integration tests for Home Assistant API
- Tests for Supabase interaction in `/ideas/audio` endpoint
- E2E tests for the dashboard flow (login → calendar → ideas)

To run tests:
```bash
# Backend tests
cd tests/backend
pytest

# Frontend tests
npx jest
```