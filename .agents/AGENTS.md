# Artifact Mirroring Rule

Whenever you create, update, or modify any artifact (such as `implementation_plan.md`, `task.md`, `walkthrough.md`, or database reviews) in the global Antigravity App Data directory, you MUST automatically mirror/write those files to the `.artifacts/` folder in the project's root directory (e.g. `PGVectorRAGIndexer/.artifacts/`). 

This ensures the user can immediately see, open, and review the artifact content directly within their IDE file tree.
