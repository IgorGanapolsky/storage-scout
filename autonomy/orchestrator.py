from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from autonomy.context_store import ContextStore
from autonomy.utils import UTC

log = logging.getLogger(__name__)

@dataclass
class OrchestrationState:
    """The persistent state passed between nodes in the orchestration graph."""
    session_id: str
    repo_root: Path
    config: Any
    env: Dict[str, str]
    sqlite_path: Path
    audit_log_path: Path
    
    # Node outputs
    leads_generated: int = 0
    leads_cleaned: int = 0
    audits_run: List[Dict[str, Any]] = field(default_factory=list)
    calls_attempted: int = 0
    sms_sent: int = 0
    nudges_sent: int = 0
    
    # Internal metrics
    errors: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    start_time: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

class Node:
    """Base class for an orchestration node."""
    def run(self, state: OrchestrationState) -> OrchestrationState:
        raise NotImplementedError

class Orchestrator:
    """Standardized dispatcher for agentic workflows."""
    def __init__(self, state: OrchestrationState):
        self.state = state
        self.nodes: List[Node] = []

    def add_node(self, node: Node) -> Orchestrator:
        self.nodes.append(node)
        return self

    def execute(self) -> OrchestrationState:
        log.info(f"Starting orchestration session {self.state.session_id}")
        for node in self.nodes:
            node_name = node.__class__.__name__
            try:
                log.info(f"Executing Node: {node_name}")
                self.state = node.run(self.state)
            except Exception as e:
                error_msg = f"Node {node_name} failed: {str(e)}"
                log.error(error_msg)
                self.state.errors.append(error_msg)
        
        self.state.metadata["completed_at"] = datetime.now(UTC).isoformat()
        return self.state

def run_state_machine(state: OrchestrationState, node_classes: List[type[Node]]) -> OrchestrationState:
    orchestrator = Orchestrator(state)
    for cls in node_classes:
        orchestrator.add_node(cls())
    return orchestrator.execute()
