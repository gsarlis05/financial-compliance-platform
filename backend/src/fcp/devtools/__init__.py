"""Developer tooling. Never invoked by the running application in any deployed environment.

``fcp.devtools`` may import ``fcp.core``, but ``fcp.core`` and ``fcp.modules`` must never import
``fcp.devtools`` (enforced by import-linter).
"""
