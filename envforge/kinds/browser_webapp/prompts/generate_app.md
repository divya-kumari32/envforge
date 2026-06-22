Build a single-page web application in the current directory from the provided
documentation. Requirements:
- Entry point `index.html` plus `js/` and `css/` as needed.
- A `server.py` that serves static files AND implements the state protocol:
  GET /api/state (current state JSON; 404 before first PUT), PUT /api/state
  (full state; first PUT is captured as the immutable seed), POST /api/reset
  (restore seed), GET /api/events (SSE reset stream).
- On first load the browser must PUT its full initial state to /api/state.
- No native dialogs (alert/confirm/<select>); use custom JS-rendered widgets.
- Rich, realistic seed data.
