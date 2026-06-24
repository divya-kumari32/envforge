Build a single-page web application in the current directory from the provided
documentation. Requirements:
- Entry point `index.html` plus `js/` and `css/` as needed.
- A `server.py` that serves static files AND implements the state protocol:
  GET /api/state (current state JSON; 404 before first PUT), PUT /api/state
  (full state; first PUT is captured as the immutable seed), POST /api/reset
  (restore seed), GET /api/events (SSE reset stream).
- No native dialogs (alert/confirm/<select>); use custom JS-rendered widgets.
- Rich, realistic seed data.

CRITICAL — seed-on-load contract (the app MUST follow this exactly, or it is
considered broken):
- On first page load, the browser JS MUST establish the seed state. Do this:
  1. `GET /api/state`.
  2. If it returns **HTTP 404** (no state yet) — detect this by the **HTTP
     status code** (`response.status === 404`), NOT by parsing the response body
     or matching an error message string — then build the full initial state and
     `PUT /api/state` with it. The first PUT is captured as the immutable seed.
  3. If it returns 200, load that state.
- Do NOT assume the 404 response has any particular body; it may be empty.
- After load, `PUT /api/state` with the complete state on every mutation.
- The app is served by an external harness, so all state lives behind
  /api/state — never rely on server.py being the process that serves the page.
