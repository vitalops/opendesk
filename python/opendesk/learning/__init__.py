"""Learning layer — verifiable rewards and goal-state anchoring.

This package holds the *environment* half of reinforcement learning for
computer-use agents.  It does not train models: given a task it produces
machine-checkable rewards, step-level process signals, episode records, and the
state diagnosis that explains where a session stalled.

Modules
-------
``rewards``      declarative, verifiable success criteria (RLVR)
``goal_state``   goal-state anchoring — score an end state against a reference
``process``      step-level process rewards derived from action effects
``trajectories`` episode lifecycle
``assertions``   claims the agent makes about the state, verified and scored

Nothing here calls a model.  Every signal is derived from observable state
(files, shell output, the accessibility tree, screenshots).
"""

from __future__ import annotations

__all__ = [
    "rewards", "goal_state", "process", "trajectories", "assertions",
]
