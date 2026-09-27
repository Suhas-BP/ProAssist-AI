"""
core/tool.py
============
Formal contract for autonomous agent tools and action dispatch.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional, Union


@dataclass
class ToolResult:
    """
    Standardized execution envelope for tool actions.
    Preserves seamless string formatting for string-based consumers while
    providing rich structured metadata for observability and planner verification.
    """
    success: bool
    tool: str
    action: Optional[str] = None
    value: Any = None
    message: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to the Phase 1/2 canonical dictionary shape."""
        return {
            "success": self.success,
            "tool": self.tool,
            "action": self.action,
            "value": self.value,
            "message": self.message,
            "error": self.error,
        }

    def __str__(self) -> str:
        """String representation returns the human-readable message or serialized value."""
        return self.message if self.message else str(self.value or "")


class AgentTool(ABC):
    """
    Abstract base class for all Mark LIV action modules.

    Guarantees:
    - Formal declaration of tool metadata (name, description, Gemini schema).
    - Unified execute() interface with signature-inspected context injection.
    - Full backward-compatibility with action_loader's legacy TOOL dictionary discovery.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier matching ^[a-zA-Z_][a-zA-Z0-9_]{0,63}$."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Natural-language description consumed by Gemini Live for tool routing."""
        pass

    @property
    def parameters(self) -> Dict[str, Any]:
        """Gemini function declaration schema. Defaults to open OBJECT."""
        return {"type": "OBJECT", "properties": {}}

    @property
    def behavior(self) -> Optional[str]:
        """BLOCKING (default) or NON_BLOCKING."""
        return None

    @property
    def scheduling(self) -> Optional[str]:
        """WHEN_IDLE (default), SILENT, or INTERRUPT."""
        return None

    @abstractmethod
    def execute(self, parameters: Dict[str, Any], **context) -> Union[str, Dict[str, Any], ToolResult]:
        """
        Execute the tool action with parameters and injected context kwargs:
        player (AgentUI), speak (Callable), response, session_memory.
        """
        pass

    def to_tool_dict(self) -> Dict[str, Any]:
        """
        Bridge method converting this AgentTool instance to the legacy TOOL
        dictionary expected by core/action_loader.py.
        """
        d = {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "handler": self.execute,
        }
        if self.behavior:
            d["behavior"] = self.behavior
        if self.scheduling:
            d["scheduling"] = self.scheduling
        return d
