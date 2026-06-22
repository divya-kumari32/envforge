Generate exactly 24 function-level tasks (8 easy, 8 medium, 8 hard) for the app
in the current directory. Write `function-tasks.json` as a JSON array; each task
object has: `id` (e.g. "task_e1"), `prompt` (instruction for a browser agent),
`difficulty` (easy|medium|hard). For each task write a verifier at
`verifiers/<id>.py` exporting `verify(server_url) -> (bool, str)` that reads
GET /api/state and checks the expected outcome (never interacts with the UI).
