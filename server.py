"""
Claude Code SDK HTTP Server

A FastAPI-based HTTP server that exposes the Claude Agent SDK as REST endpoints.
Supports session management, streaming responses, and custom tools.
"""

import asyncio
import logging
import os
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Depends, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    tool,
    create_sdk_mcp_server,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
)


# ============================================================================
# Custom Tools Definition
# ============================================================================

@tool("get_server_time", "Get current server time", {})
async def get_server_time(args: dict[str, Any]) -> dict[str, Any]:
    """Return current server time."""
    from datetime import datetime
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "content": [{
            "type": "text",
            "text": f"Server time: {current_time}"
        }]
    }


@tool("calculate", "Perform mathematical calculations", {"expression": str})
async def calculate(args: dict[str, Any]) -> dict[str, Any]:
    """Safely evaluate mathematical expressions."""
    import ast
    import operator

    # Safe evaluation using ast
    allowed_operators = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
    }

    def safe_eval(node):
        if isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type not in allowed_operators:
                raise ValueError(f"Operator not allowed: {op_type}")
            return allowed_operators[op_type](
                safe_eval(node.left),
                safe_eval(node.right)
            )
        elif isinstance(node, ast.UnaryOp):
            op_type = type(node.op)
            if op_type not in allowed_operators:
                raise ValueError(f"Operator not allowed: {op_type}")
            return allowed_operators[op_type](safe_eval(node.operand))
        else:
            raise ValueError(f"Expression type not allowed: {type(node)}")

    try:
        tree = ast.parse(args["expression"], mode="eval")
        result = safe_eval(tree.body)
        return {
            "content": [{
                "type": "text",
                "text": f"Result: {result}"
            }]
        }
    except Exception as e:
        return {
            "content": [{
                "type": "text",
                "text": f"Error: {str(e)}"
            }],
            "is_error": True
        }


# Create custom MCP server with tools
custom_tools_server = create_sdk_mcp_server(
    name="server_tools",
    version="1.0.0",
    tools=[get_server_time, calculate]
)


# ============================================================================
# Workspace Management
# ============================================================================

logger = logging.getLogger(__name__)


class WorkspaceManager:
    """Manages temporary working directories for queries and sessions."""

    def __init__(self):
        self.base_dir = Path.home() / ".claude" / "workspaces"
        self._lock = asyncio.Lock()
        self.workspace_owners: dict[str, str] = {}  # identifier -> owner_type

    async def initialize(self) -> None:
        """
        Initialize workspace manager.

        - Creates base workspace directory if it doesn't exist
        - Cleans up orphaned workspaces (older than 24 hours)
        """
        try:
            # Create base directory
            self.base_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Workspace base directory: {self.base_dir}")

            # Cleanup orphaned workspaces
            await self._cleanup_orphaned_workspaces()

        except Exception as e:
            logger.error(f"Failed to initialize workspace manager: {e}")
            raise

    async def _cleanup_orphaned_workspaces(self) -> None:
        """Remove workspace directories older than 24 hours."""
        if not self.base_dir.exists():
            return

        import time
        current_time = time.time()
        max_age_seconds = 24 * 3600  # 24 hours

        try:
            for workspace_path in self.base_dir.iterdir():
                if not workspace_path.is_dir():
                    continue

                # Check age of directory
                dir_mtime = workspace_path.stat().st_mtime
                age_seconds = current_time - dir_mtime

                if age_seconds > max_age_seconds:
                    try:
                        shutil.rmtree(workspace_path)
                        age_hours = age_seconds / 3600
                        logger.info(
                            f"Removed orphaned workspace: {workspace_path.name} "
                            f"(age: {age_hours:.1f}h)"
                        )
                    except Exception as e:
                        logger.warning(
                            f"Failed to remove orphaned workspace {workspace_path}: {e}"
                        )

        except Exception as e:
            logger.warning(f"Error during orphaned workspace cleanup: {e}")

    async def create_workspace(self, identifier: str, owner_type: str) -> str:
        """
        Create a new workspace directory.

        Args:
            identifier: Unique identifier (UUID for queries, session_id for sessions)
            owner_type: Type of owner ("query", "query_stream", "session")

        Returns:
            Absolute path to the created workspace directory

        Raises:
            Exception: If workspace creation fails
        """
        async with self._lock:
            workspace_path = self.base_dir / identifier

            try:
                # Create workspace directory
                workspace_path.mkdir(parents=True, exist_ok=False)

                # Track ownership
                self.workspace_owners[identifier] = owner_type

                logger.info(
                    f"Created workspace: {workspace_path} for {owner_type}:{identifier}"
                )

                return str(workspace_path)

            except FileExistsError:
                logger.warning(f"Workspace already exists: {workspace_path}")
                # Track ownership anyway
                self.workspace_owners[identifier] = owner_type
                return str(workspace_path)

            except Exception as e:
                logger.error(f"Failed to create workspace {workspace_path}: {e}")
                raise

    async def cleanup_workspace(self, identifier: str) -> bool:
        """
        Remove a workspace directory.

        Args:
            identifier: The workspace identifier to cleanup

        Returns:
            True if workspace was cleaned up, False otherwise
        """
        async with self._lock:
            # Check if we track this workspace
            if identifier not in self.workspace_owners:
                logger.debug(f"Workspace {identifier} not tracked, skipping cleanup")
                return False

            workspace_path = self.base_dir / identifier
            owner_type = self.workspace_owners[identifier]

            # Remove from tracking first
            del self.workspace_owners[identifier]

        # Delete directory outside lock to avoid blocking
        try:
            if workspace_path.exists():
                shutil.rmtree(workspace_path)
                logger.info(f"Cleaned workspace: {workspace_path} ({owner_type})")
                return True
            else:
                logger.debug(f"Workspace {workspace_path} doesn't exist, skipping")
                return False

        except Exception as e:
            logger.warning(f"Failed to cleanup workspace {workspace_path}: {e}")
            return False

    async def cleanup_all(self) -> None:
        """Emergency cleanup of all tracked workspaces."""
        async with self._lock:
            identifiers = list(self.workspace_owners.keys())

        logger.info(f"Cleaning up {len(identifiers)} tracked workspaces")

        for identifier in identifiers:
            try:
                await self.cleanup_workspace(identifier)
            except Exception as e:
                logger.error(f"Error cleaning workspace {identifier}: {e}")


# ============================================================================
# Validation Functions
# ============================================================================

def validate_output_format(output_format: dict[str, Any] | None) -> None:
    """
    Validate output_format structure before passing to SDK.

    Raises HTTPException if format is invalid.
    """
    if output_format is None:
        return

    if not isinstance(output_format, dict):
        raise HTTPException(
            status_code=422,
            detail="output_format must be a dictionary"
        )

    if "type" not in output_format:
        raise HTTPException(
            status_code=422,
            detail="output_format must contain 'type' field"
        )

    if output_format["type"] != "json_schema":
        raise HTTPException(
            status_code=422,
            detail="output_format type must be 'json_schema'"
        )

    # Support OpenAI-style nested format: {"type": "json_schema", "json_schema": {"name": "...", "schema": {...}}}
    # Normalize it to the flat format: {"type": "json_schema", "schema": {...}}
    if "schema" not in output_format and "json_schema" in output_format:
        json_schema_wrapper = output_format["json_schema"]
        if not isinstance(json_schema_wrapper, dict):
            raise HTTPException(
                status_code=422,
                detail="output_format json_schema must be a dictionary"
            )
        if "schema" not in json_schema_wrapper:
            raise HTTPException(
                status_code=422,
                detail="output_format json_schema must contain 'schema' field"
            )
        # Normalize: hoist schema to top level and remove the wrapper
        output_format["schema"] = json_schema_wrapper["schema"]
        del output_format["json_schema"]

    if "schema" not in output_format:
        raise HTTPException(
            status_code=422,
            detail="output_format must contain 'schema' field (either at top level or inside 'json_schema')"
        )

    schema = output_format["schema"]
    if not isinstance(schema, dict):
        raise HTTPException(
            status_code=422,
            detail="output_format schema must be a dictionary"
        )


# ============================================================================
# Session Management
# ============================================================================

class SessionManager:
    """Manages active Claude SDK sessions."""

    def __init__(self):
        self.sessions: dict[str, ClaudeSDKClient] = {}
        self.session_workspaces: dict[str, str] = {}  # session_id -> workspace_path
        self.created_workspaces: set[str] = set()  # sessions where we created workspace
        self._lock = asyncio.Lock()

    async def create_session(
        self,
        session_id: str | None = None,
        options: ClaudeAgentOptions | None = None,
        workspace_path: str | None = None
    ) -> str:
        """
        Create a new session and return its ID.

        Args:
            session_id: Optional session ID (generated if not provided)
            options: Claude agent options
            workspace_path: Optional workspace path (if we created it)
        """
        if session_id is None:
            session_id = str(uuid.uuid4())

        async with self._lock:
            if session_id in self.sessions:
                raise ValueError(f"Session {session_id} already exists")

            client = ClaudeSDKClient(options)
            await client.connect()
            self.sessions[session_id] = client

            # Track workspace if we created it
            if workspace_path is not None:
                self.session_workspaces[session_id] = workspace_path
                self.created_workspaces.add(session_id)

        return session_id

    async def get_session(self, session_id: str) -> ClaudeSDKClient:
        """Get an existing session."""
        async with self._lock:
            if session_id not in self.sessions:
                raise KeyError(f"Session {session_id} not found")
            return self.sessions[session_id]

    async def close_session(self, session_id: str) -> None:
        """Close and remove a session."""
        should_cleanup_workspace = False

        async with self._lock:
            if session_id in self.sessions:
                client = self.sessions.pop(session_id)
                await client.disconnect()

                # Check if we need to cleanup workspace
                if session_id in self.created_workspaces:
                    self.created_workspaces.discard(session_id)
                    self.session_workspaces.pop(session_id, None)
                    should_cleanup_workspace = True

        # Cleanup workspace outside lock
        if should_cleanup_workspace:
            await workspace_manager.cleanup_workspace(session_id)

    async def close_all(self) -> None:
        """Close all sessions."""
        async with self._lock:
            for client in self.sessions.values():
                try:
                    await client.disconnect()
                except Exception:
                    pass
            self.sessions.clear()
            self.session_workspaces.clear()
            self.created_workspaces.clear()

        # Cleanup all workspaces
        await workspace_manager.cleanup_all()


# Global managers
session_manager = SessionManager()
workspace_manager = WorkspaceManager()


# ============================================================================
# FastAPI Application
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup: Initialize workspace manager
    await workspace_manager.initialize()

    yield

    # Shutdown: Cleanup in order
    await session_manager.close_all()
    await workspace_manager.cleanup_all()


app = FastAPI(
    title="Claude Code SDK Server",
    description="HTTP server exposing Claude Agent SDK capabilities",
    version="1.0.0",
    lifespan=lifespan,
    swagger_ui_parameters={
        "defaultModelsExpandDepth": 3,
        "defaultModelRendering": "model",
    }
)


# ============================================================================
# Authentication
# ============================================================================

security = HTTPBearer(auto_error=False)


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(security)
) -> None:
    """
    Verify API key from Bearer token.

    Raises:
        HTTPException: 401 if credentials missing, 403 if invalid
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Load API_KEY at runtime to support hot-reloading
    api_key = os.getenv("API_KEY")

    if api_key is None:
        # Authentication disabled if API_KEY not set
        logger.warning("API_KEY not set - authentication disabled (development only)")
        return

    if credentials.credentials != api_key:
        logger.warning("Failed authentication attempt")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid authentication credentials",
        )


# ============================================================================
# Request/Response Models
# ============================================================================

class QueryRequest(BaseModel):
    """Request model for one-shot queries."""
    prompt: str = Field(
        ...,
        description="The main instruction or question to send to the Claude agent. "
                    "This is the user message that drives the agent's behavior."
    )
    system_prompt: str | None = Field(
        None,
        description="Optional system prompt that sets the agent's persona, behavior, and context. "
                    "Injected before the conversation to guide Claude's responses "
                    "(e.g., 'You are a senior Python developer')."
    )
    max_turns: int | None = Field(
        None,
        description="Maximum number of agentic turns (LLM call + tool execution cycles) allowed. "
                    "null = unlimited turns. Each turn consists of one LLM inference "
                    "and any resulting tool executions. Use to prevent runaway agents.",
        ge=1
    )
    allowed_tools: list[str] = Field(
        default=["Read", "Grep", "Glob"],
        description="List of tool names the agent is permitted to use. "
                    "Standard tools: 'Read' (read file contents), 'Write' (create/overwrite files), "
                    "'Edit' (edit existing files), 'Bash' (execute shell commands), "
                    "'Grep' (search file contents), 'Glob' (find files by pattern), "
                    "'Skill' (use loaded skills). "
                    "Custom MCP tools use the format 'mcp__<server_name>__<tool_name>' "
                    "(e.g., 'mcp__tools__calculate'). "
                    "When include_custom_tools is true, 'mcp__tools__get_server_time' and "
                    "'mcp__tools__calculate' are automatically appended.",
        examples=[["Read", "Grep", "Glob"], ["Read", "Write", "Edit", "Bash", "Grep", "Glob"]]
    )
    permission_mode: str | None = Field(
        None,
        description="Controls how Claude handles tool permission checks. Valid values: "
                    "'default' (standard restrictions, unmatched tools require approval), "
                    "'acceptEdits' (auto-accept file edits and filesystem ops like mkdir/rm/mv/cp), "
                    "'plan' (planning only, no tool execution allowed), "
                    "'bypassPermissions' (all tools run without prompts — use with caution, "
                    "subagents inherit this mode). "
                    "null = server does not set a mode (SDK default behavior).",
        examples=["default", "acceptEdits", "plan", "bypassPermissions"],
        json_schema_extra={"enum": [None, "default", "acceptEdits", "plan", "bypassPermissions"]}
    )
    cwd: str | None = Field(
        None,
        description="Absolute path to the working directory for the agent. "
                    "Used as the root for all file operations (Read, Write, Edit, Glob, etc.). "
                    "null = server's current working directory.",
        examples=["/workspace", "/home/user/project"]
    )
    include_custom_tools: bool = Field(
        True,
        description="Whether to include the server's built-in custom MCP tools: "
                    "'mcp__tools__get_server_time' (returns current server timestamp) and "
                    "'mcp__tools__calculate' (safe mathematical expression evaluator). "
                    "When true, these tools are automatically added to allowed_tools."
    )
    skills: list[str] = Field(
        default=[],
        description="List of skill directory names to enable for the agent. "
                    "Skills are discovered from '~/.claude/skills/<name>/SKILL.md' (user-level) "
                    "and '{cwd}/.claude/skills/<name>/SKILL.md' (project-level). "
                    "When skills are specified, the 'Skill' tool is automatically added to allowed_tools. "
                    "Use GET /skills?cwd=<path> to discover available skill names.",
        examples=[["pdf-processor", "code-review"]]
    )
    setting_sources: list[str] = Field(
        default=[],
        description="Sources to load skill settings from. Valid values: "
                    "'user' (load from ~/.claude/skills/), "
                    "'project' (load from {cwd}/.claude/skills/). "
                    "If skills are specified but setting_sources is empty, defaults to ['user', 'project'].",
        examples=[["user", "project"], ["user"], ["project"]]
    )
    output_format: dict[str, Any] | None = Field(
        None,
        description="Structured output format configuration. When provided, Claude returns "
                    "validated JSON matching your schema. Required structure: "
                    "{'type': 'json_schema', 'schema': {<JSON Schema object>}}. "
                    "The 'type' field must be 'json_schema'. "
                    "The 'schema' field must be a valid JSON Schema object with 'type', 'properties', etc. "
                    "Response will include 'structured_output' (the parsed data) and "
                    "'subtype' ('success' or 'error_max_structured_output_retries').",
        examples=[{
            "type": "json_schema",
            "schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "score": {"type": "number"}
                },
                "required": ["summary"]
            }
        }]
    )


class QueryResponse(BaseModel):
    """Response model for queries."""
    result: str | None = Field(
        None,
        description="Final text result from the agent. May be null when structured_output "
                    "is used instead, or if the agent produced no text output."
    )
    session_id: str = Field(
        ...,
        description="UUID of the session used for this query. Can be used to identify "
                    "the conversation context. Format: UUID v4 (e.g., '550e8400-e29b-41d4-a716-446655440000')."
    )
    is_error: bool = Field(
        False,
        description="Whether the agent encountered an unrecoverable error during execution. "
                    "true = the query failed; check 'result' for error details."
    )
    total_cost_usd: float | None = Field(
        None,
        description="Cumulative Anthropic API cost in USD for all turns in this query. "
                    "null if cost tracking is unavailable."
    )
    duration_ms: int | None = Field(
        None,
        description="Wall-clock time in milliseconds for the entire query execution, "
                    "including all agent turns, tool calls, and processing."
    )
    structured_output: dict[str, Any] | None = Field(
        None,
        description="Validated structured output matching the JSON schema provided in "
                    "the request's output_format. Only populated when output_format was "
                    "specified and validation succeeded (subtype='success'). "
                    "null if no output_format was requested or validation failed."
    )
    subtype: str | None = Field(
        None,
        description="Result subtype indicating structured output validation status. "
                    "Valid values: 'success' (output generated and validated successfully), "
                    "'error_max_structured_output_retries' (could not produce valid output "
                    "after maximum retry attempts). null if output_format was not used.",
        examples=["success", "error_max_structured_output_retries"]
    )


class SessionRequest(BaseModel):
    """Request model for creating persistent sessions that maintain conversation context across multiple chat messages."""
    system_prompt: str | None = Field(
        None,
        description="Optional system prompt that sets the agent's persona, behavior, and context "
                    "for the entire session. Applied to all messages in this session "
                    "(e.g., 'You are a helpful coding assistant specialized in Python')."
    )
    allowed_tools: list[str] = Field(
        default=["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
        description="List of tool names the agent is permitted to use during this session. "
                    "Default includes all standard tools for full development capability. "
                    "Standard tools: 'Read' (read file contents), 'Write' (create/overwrite files), "
                    "'Edit' (edit existing files), 'Bash' (execute shell commands), "
                    "'Grep' (search file contents), 'Glob' (find files by pattern), "
                    "'Skill' (use loaded skills). "
                    "Custom MCP tools use the format 'mcp__<server_name>__<tool_name>'. "
                    "Note: session default includes Write/Edit/Bash (unlike one-shot query).",
        examples=[["Read", "Write", "Edit", "Bash", "Grep", "Glob"], ["Read", "Grep", "Glob"]]
    )
    permission_mode: str = Field(
        "acceptEdits",
        description="Controls how Claude handles tool permission checks for this session. "
                    "Valid values: "
                    "'default' (standard restrictions, unmatched tools require approval), "
                    "'acceptEdits' (auto-accept file edits and filesystem ops like mkdir/rm/mv/cp), "
                    "'plan' (planning only, no tool execution allowed), "
                    "'bypassPermissions' (all tools run without prompts — use with caution, "
                    "subagents inherit this mode). "
                    "Note: sessions default to 'acceptEdits' (unlike one-shot query which defaults to null).",
        examples=["default", "acceptEdits", "plan", "bypassPermissions"],
        json_schema_extra={"enum": ["default", "acceptEdits", "plan", "bypassPermissions"]}
    )
    cwd: str | None = Field(
        None,
        description="Absolute path to the working directory for the session. "
                    "Used as root for all file operations throughout the session. "
                    "null = server's current working directory.",
        examples=["/workspace", "/home/user/project"]
    )
    include_custom_tools: bool = Field(
        True,
        description="Whether to include the server's built-in custom MCP tools: "
                    "'mcp__tools__get_server_time' (returns current server timestamp) and "
                    "'mcp__tools__calculate' (safe mathematical expression evaluator). "
                    "When true, these tools are automatically added to allowed_tools."
    )
    skills: list[str] = Field(
        default=[],
        description="List of skill directory names to enable for this session. "
                    "Skills are discovered from '~/.claude/skills/<name>/SKILL.md' (user-level) "
                    "and '{cwd}/.claude/skills/<name>/SKILL.md' (project-level). "
                    "When skills are specified, the 'Skill' tool is automatically added to allowed_tools. "
                    "Use GET /skills?cwd=<path> to discover available skill names.",
        examples=[["pdf-processor", "code-review"]]
    )
    setting_sources: list[str] = Field(
        default=[],
        description="Sources to load skill settings from. Valid values: "
                    "'user' (load from ~/.claude/skills/), "
                    "'project' (load from {cwd}/.claude/skills/). "
                    "If skills are specified but setting_sources is empty, defaults to ['user', 'project'].",
        examples=[["user", "project"], ["user"], ["project"]]
    )
    output_format: dict[str, Any] | None = Field(
        None,
        description="Structured output format configuration for all responses in this session. "
                    "When provided, all chat responses will include validated JSON matching your schema. "
                    "Required structure: {'type': 'json_schema', 'schema': {<JSON Schema object>}}. "
                    "The 'type' field must be 'json_schema'. "
                    "The 'schema' field must be a valid JSON Schema object. "
                    "Chat responses will include 'structured_output' and 'subtype' fields.",
        examples=[{
            "type": "json_schema",
            "schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "score": {"type": "number"}
                },
                "required": ["summary"]
            }
        }]
    )


class SessionResponse(BaseModel):
    """Response model for session creation and deletion."""
    session_id: str = Field(
        ...,
        description="UUID v4 identifier for the session. Use this in session endpoints: "
                    "POST /sessions/{session_id}/chat, POST /sessions/{session_id}/chat/stream, "
                    "POST /sessions/{session_id}/interrupt, DELETE /sessions/{session_id}.",
        examples=["550e8400-e29b-41d4-a716-446655440000"]
    )
    status: str = Field(
        ...,
        description="Current session status. Valid values: "
                    "'created' (session successfully created and ready for chat), "
                    "'deleted' (session closed and resources released).",
        examples=["created", "deleted"],
        json_schema_extra={"enum": ["created", "deleted"]}
    )


class ChatRequest(BaseModel):
    """Request model for sending a message within an active session."""
    message: str = Field(
        ...,
        description="The user message to send within the active session context. "
                    "The session maintains conversation history, so Claude remembers "
                    "all previous messages exchanged in this session."
    )


class ChatResponse(BaseModel):
    """Response model for non-streaming chat messages."""
    response: str = Field(
        ...,
        description="Concatenated text from all assistant message blocks in this response. "
                    "Contains Claude's full text reply for this chat turn."
    )
    is_complete: bool = Field(
        True,
        description="Whether the response is complete. Always true for non-streaming responses. "
                    "For streaming responses, use the SSE 'done' event instead."
    )
    structured_output: dict[str, Any] | None = Field(
        None,
        description="Validated structured output matching the JSON schema configured in the session's "
                    "output_format. Only present when the session was created with output_format "
                    "and validation succeeded (subtype='success'). null otherwise."
    )
    subtype: str | None = Field(
        None,
        description="Structured output validation status. Valid values: "
                    "'success' (output generated and validated successfully), "
                    "'error_max_structured_output_retries' (could not produce valid output "
                    "after maximum retry attempts). null if session has no output_format.",
        examples=["success", "error_max_structured_output_retries"]
    )


class MessageContent(BaseModel):
    """Model for individual content blocks in streaming responses."""
    type: str = Field(
        ...,
        description="Content block type. Valid values: "
                    "'text' (text content from Claude), "
                    "'tool_use' (Claude is calling a tool), "
                    "'tool_result' (result from a tool execution), "
                    "'result' (final result with cost/session info), "
                    "'done' (session chat completion marker), "
                    "'error' (an error occurred).",
        examples=["text", "tool_use", "tool_result", "result", "done", "error"]
    )
    text: str | None = Field(
        None,
        description="Text content. Present when type='text' (Claude's response text) "
                    "or type='error' (error message)."
    )
    tool_name: str | None = Field(
        None,
        description="Name of the tool being called. Present when type='tool_use'. "
                    "Uses the same tool name format as allowed_tools "
                    "(e.g., 'Read', 'mcp__tools__calculate')."
    )
    tool_input: dict | None = Field(
        None,
        description="Input arguments passed to the tool. Present when type='tool_use'. "
                    "Structure varies by tool."
    )


class SkillInfo(BaseModel):
    """Information about a single discovered skill."""
    name: str = Field(
        ...,
        description="Skill name, which is the directory name under the skills folder. "
                    "Use this value in the 'skills' field of QueryRequest or SessionRequest.",
        examples=["pdf-processor", "code-review"]
    )
    description: str | None = Field(
        None,
        description="Human-readable skill description extracted from the YAML frontmatter "
                    "'description' field in the skill's SKILL.md file. null if no frontmatter found."
    )
    location: str = Field(
        ...,
        description="Where the skill was discovered from. Valid values: "
                    "'user' (from ~/.claude/skills/<name>/SKILL.md), "
                    "'project' (from {cwd}/.claude/skills/<name>/SKILL.md).",
        examples=["user", "project"],
        json_schema_extra={"enum": ["user", "project"]}
    )
    path: str = Field(
        ...,
        description="Full absolute filesystem path to the skill's SKILL.md file.",
        examples=["/home/user/.claude/skills/pdf-processor/SKILL.md"]
    )


class SkillsListResponse(BaseModel):
    """Response containing all discovered skills from user and project directories."""
    skills: list[SkillInfo] = Field(
        default_factory=list,
        description="List of discovered skills. Empty if no skills found in either location."
    )
    count: int = Field(
        0,
        description="Total number of skills discovered across both user and project directories."
    )
    cwd: str | None = Field(
        None,
        description="The working directory that was used to search for project-level skills "
                    "(i.e., {cwd}/.claude/skills/). Same value as the 'cwd' query parameter."
    )


# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "claude-sdk-server"}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


def _extract_description(skill_file) -> str | None:
    """Extract description from SKILL.md YAML frontmatter."""
    try:
        import yaml
        content = skill_file.read_text(encoding='utf-8')
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                frontmatter = yaml.safe_load(parts[1])
                return frontmatter.get('description')
    except Exception:
        pass
    return None


@app.get("/skills", response_model=SkillsListResponse)
async def list_skills(
    cwd: str | None = Query(None, description="Working directory for project skills"),
    _: None = Depends(verify_api_key)
):
    """
    List available skills from user and project directories.

    Skills are discovered from:
    - User: ~/.claude/skills/*/SKILL.md (always included)
    - Project: {cwd}/.claude/skills/*/SKILL.md (only if cwd provided)
    """
    from pathlib import Path

    skills = []

    # User skills (~/.claude/skills/) - always included
    user_skills_dir = Path.home() / ".claude" / "skills"
    if user_skills_dir.exists():
        for skill_dir in user_skills_dir.iterdir():
            skill_file = skill_dir / "SKILL.md"
            if skill_dir.is_dir() and skill_file.exists():
                skills.append(SkillInfo(
                    name=skill_dir.name,
                    description=_extract_description(skill_file),
                    location="user",
                    path=str(skill_file)
                ))

    # Project skills ({cwd}/.claude/skills/) - only if cwd provided
    if cwd:
        project_skills_dir = Path(cwd) / ".claude" / "skills"
        if project_skills_dir.exists():
            for skill_dir in project_skills_dir.iterdir():
                skill_file = skill_dir / "SKILL.md"
                if skill_dir.is_dir() and skill_file.exists():
                    skills.append(SkillInfo(
                        name=skill_dir.name,
                        description=_extract_description(skill_file),
                        location="project",
                        path=str(skill_file)
                    ))

    return SkillsListResponse(skills=skills, count=len(skills), cwd=cwd)


@app.post("/query", response_model=QueryResponse)
async def single_query(
    request: QueryRequest,
    _: None = Depends(verify_api_key)
):
    """
    Execute a one-shot query to Claude.

    This creates a new session for each request and returns the final result.
    Good for stateless, one-off tasks.
    """
    import traceback

    # Validate output_format if provided
    validate_output_format(request.output_format)

    # Generate workspace ID and prepare for cleanup
    workspace_id = str(uuid.uuid4())
    workspace_path = None

    try:
        # Create temporary workspace
        workspace_path = await workspace_manager.create_workspace(
            workspace_id,
            owner_type="query"
        )

        # Build options
        mcp_servers = {}
        allowed_tools = list(request.allowed_tools)

        if request.include_custom_tools:
            mcp_servers["tools"] = custom_tools_server
            allowed_tools.extend([
                "mcp__tools__get_server_time",
                "mcp__tools__calculate"
            ])

        # Enable skills if specified
        setting_sources = None
        if request.skills or request.setting_sources:
            # Add "Skill" tool if not already present
            if "Skill" not in allowed_tools:
                allowed_tools.append("Skill")
            # Set setting_sources (default to both if skills specified)
            setting_sources = request.setting_sources if request.setting_sources else ["user", "project"]

        options = ClaudeAgentOptions(
            system_prompt=request.system_prompt,
            max_turns=request.max_turns,
            allowed_tools=allowed_tools,
            permission_mode=request.permission_mode,
            cwd=workspace_path,  # Use temporary workspace
            mcp_servers=mcp_servers if mcp_servers else None,
            setting_sources=setting_sources,
            output_format=request.output_format
        )

        result_text = None
        session_id = None
        is_error = False
        total_cost = None
        duration = None
        structured_output = None
        subtype = None

        async with ClaudeSDKClient(options=options) as client:
            await client.query(request.prompt)

            async for message in client.receive_response():
                if isinstance(message, ResultMessage):
                    result_text = message.result
                    session_id = message.session_id
                    is_error = message.is_error
                    total_cost = message.total_cost_usd
                    duration = message.duration_ms
                    structured_output = message.structured_output
                    subtype = message.subtype
                elif isinstance(message, AssistantMessage):
                    # Capture the last assistant message text if no result
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            result_text = block.text

        return QueryResponse(
            result=result_text,
            session_id=session_id or str(uuid.uuid4()),
            is_error=is_error,
            total_cost_usd=total_cost,
            duration_ms=duration,
            structured_output=structured_output,
            subtype=subtype
        )

    except Exception as e:
        print(f"Query error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # CRITICAL: Always cleanup workspace
        if workspace_path:
            await workspace_manager.cleanup_workspace(workspace_id)


@app.post("/query/stream")
async def stream_query(
    request: QueryRequest,
    _: None = Depends(verify_api_key)
):
    """
    Execute a streaming query to Claude.

    Returns a stream of server-sent events (SSE) with real-time responses.
    """
    # Validate output_format if provided
    validate_output_format(request.output_format)

    # Generate workspace ID and create workspace
    workspace_id = str(uuid.uuid4())
    workspace_path = await workspace_manager.create_workspace(
        workspace_id,
        owner_type="query_stream"
    )

    # Build options
    mcp_servers = {}
    allowed_tools = list(request.allowed_tools)

    if request.include_custom_tools:
        mcp_servers["tools"] = custom_tools_server
        allowed_tools.extend([
            "mcp__tools__get_server_time",
            "mcp__tools__calculate"
        ])

    # Enable skills if specified
    setting_sources = None
    if request.skills or request.setting_sources:
        # Add "Skill" tool if not already present
        if "Skill" not in allowed_tools:
            allowed_tools.append("Skill")
        # Set setting_sources (default to both if skills specified)
        setting_sources = request.setting_sources if request.setting_sources else ["user", "project"]

    options = ClaudeAgentOptions(
        system_prompt=request.system_prompt,
        max_turns=request.max_turns,
        allowed_tools=allowed_tools,
        permission_mode=request.permission_mode,
        cwd=workspace_path,  # Use temporary workspace
        mcp_servers=mcp_servers if mcp_servers else None,
        setting_sources=setting_sources,
        output_format=request.output_format
    )

    async def generate():
        import json
        try:
            async with ClaudeSDKClient(options=options) as client:
                await client.query(request.prompt)

                async for message in client.receive_response():
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                yield f"data: {json.dumps({'type': 'text', 'text': block.text})}\n\n"
                            elif isinstance(block, ToolUseBlock):
                                yield f"data: {json.dumps({'type': 'tool_use', 'name': block.name, 'input': block.input})}\n\n"
                            elif isinstance(block, ToolResultBlock):
                                yield f"data: {json.dumps({'type': 'tool_result', 'tool_use_id': block.tool_use_id})}\n\n"
                    elif isinstance(message, ResultMessage):
                        result_data = {
                            'type': 'result',
                            'result': message.result,
                            'session_id': message.session_id,
                            'is_error': message.is_error,
                            'cost': message.total_cost_usd,
                            'structured_output': message.structured_output,
                            'subtype': message.subtype
                        }
                        yield f"data: {json.dumps(result_data)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
        finally:
            # CRITICAL: Cleanup workspace after streaming completes
            await workspace_manager.cleanup_workspace(workspace_id)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.post("/sessions", response_model=SessionResponse)
async def create_session(
    request: SessionRequest,
    _: None = Depends(verify_api_key)
):
    """
    Create a new persistent session.

    Sessions maintain conversation context across multiple messages.
    """
    # Validate output_format if provided
    validate_output_format(request.output_format)

    # Generate session ID first
    session_id = str(uuid.uuid4())
    workspace_path = None
    created_workspace = False

    try:
        # Conditional workspace creation
        if request.cwd is None:
            # Create workspace with session ID as name
            workspace_path = await workspace_manager.create_workspace(
                session_id,
                owner_type="session"
            )
            created_workspace = True
        else:
            # Use user-provided cwd
            workspace_path = request.cwd
            created_workspace = False

        # Build options
        mcp_servers = {}
        allowed_tools = list(request.allowed_tools)

        if request.include_custom_tools:
            mcp_servers["tools"] = custom_tools_server
            allowed_tools.extend([
                "mcp__tools__get_server_time",
                "mcp__tools__calculate"
            ])

        # Enable skills if specified
        setting_sources = None
        if request.skills or request.setting_sources:
            # Add "Skill" tool if not already present
            if "Skill" not in allowed_tools:
                allowed_tools.append("Skill")
            # Set setting_sources (default to both if skills specified)
            setting_sources = request.setting_sources if request.setting_sources else ["user", "project"]

        options = ClaudeAgentOptions(
            system_prompt=request.system_prompt,
            allowed_tools=allowed_tools,
            permission_mode=request.permission_mode,
            cwd=workspace_path,
            mcp_servers=mcp_servers if mcp_servers else None,
            setting_sources=setting_sources,
            output_format=request.output_format
        )

        # Create session with workspace tracking
        await session_manager.create_session(
            session_id=session_id,
            options=options,
            workspace_path=workspace_path if created_workspace else None
        )

        return SessionResponse(session_id=session_id, status="created")

    except Exception as e:
        # Cleanup workspace if session creation failed
        if created_workspace and workspace_path:
            await workspace_manager.cleanup_workspace(session_id)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/sessions/{session_id}", response_model=SessionResponse)
async def delete_session(
    session_id: str,
    _: None = Depends(verify_api_key)
):
    """Close and delete a session."""
    try:
        await session_manager.close_session(session_id)
        return SessionResponse(session_id=session_id, status="deleted")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sessions/{session_id}/chat", response_model=ChatResponse)
async def chat(
    session_id: str,
    request: ChatRequest,
    _: None = Depends(verify_api_key)
):
    """
    Send a message in an existing session.

    The session maintains conversation context, so Claude remembers
    previous messages.
    """
    try:
        client = await session_manager.get_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    try:
        await client.query(request.message)

        response_text = ""
        structured_output = None
        subtype = None

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        response_text += block.text
            elif isinstance(message, ResultMessage):
                structured_output = message.structured_output
                subtype = message.subtype

        return ChatResponse(
            response=response_text,
            structured_output=structured_output,
            subtype=subtype
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sessions/{session_id}/chat/stream")
async def chat_stream(
    session_id: str,
    request: ChatRequest,
    _: None = Depends(verify_api_key)
):
    """
    Send a message and stream the response.

    Returns server-sent events (SSE) with real-time response chunks.
    """
    try:
        client = await session_manager.get_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    async def generate():
        import json
        try:
            await client.query(request.message)

            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            yield f"data: {json.dumps({'type': 'text', 'text': block.text})}\n\n"
                        elif isinstance(block, ToolUseBlock):
                            yield f"data: {json.dumps({'type': 'tool_use', 'name': block.name})}\n\n"
                elif isinstance(message, ResultMessage):
                    done_data = {
                        'type': 'done',
                        'session_id': session_id,
                        'structured_output': message.structured_output,
                        'subtype': message.subtype
                    }
                    yield f"data: {json.dumps(done_data)}\n\n"

            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.post("/sessions/{session_id}/interrupt")
async def interrupt_session(
    session_id: str,
    _: None = Depends(verify_api_key)
):
    """Interrupt the current task in a session."""
    try:
        client = await session_manager.get_session(session_id)
        await client.interrupt()
        return {"status": "interrupted", "session_id": session_id}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sessions")
async def list_sessions(_: None = Depends(verify_api_key)):
    """List all active sessions."""
    return {
        "sessions": list(session_manager.sessions.keys()),
        "count": len(session_manager.sessions)
    }


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    import os
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    api_key = os.getenv("API_KEY")

    # Log authentication status
    if api_key:
        logger.info("🔒 API authentication enabled")
    else:
        logger.warning("⚠️  API_KEY not set - authentication disabled (development only)")

    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=port,
        reload=False
    )
