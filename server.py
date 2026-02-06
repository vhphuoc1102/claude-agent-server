"""
Claude Code SDK HTTP Server

A FastAPI-based HTTP server that exposes the Claude Agent SDK as REST endpoints.
Supports session management, streaming responses, and custom tools.
"""

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
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

    if "schema" not in output_format:
        raise HTTPException(
            status_code=422,
            detail="output_format must contain 'schema' field"
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
        self._lock = asyncio.Lock()

    async def create_session(
        self,
        session_id: str | None = None,
        options: ClaudeAgentOptions | None = None
    ) -> str:
        """Create a new session and return its ID."""
        if session_id is None:
            session_id = str(uuid.uuid4())

        async with self._lock:
            if session_id in self.sessions:
                raise ValueError(f"Session {session_id} already exists")

            client = ClaudeSDKClient(options)
            await client.connect()
            self.sessions[session_id] = client

        return session_id

    async def get_session(self, session_id: str) -> ClaudeSDKClient:
        """Get an existing session."""
        async with self._lock:
            if session_id not in self.sessions:
                raise KeyError(f"Session {session_id} not found")
            return self.sessions[session_id]

    async def close_session(self, session_id: str) -> None:
        """Close and remove a session."""
        async with self._lock:
            if session_id in self.sessions:
                client = self.sessions.pop(session_id)
                await client.disconnect()

    async def close_all(self) -> None:
        """Close all sessions."""
        async with self._lock:
            for client in self.sessions.values():
                try:
                    await client.disconnect()
                except Exception:
                    pass
            self.sessions.clear()


# Global session manager
session_manager = SessionManager()


# ============================================================================
# FastAPI Application
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    yield
    # Cleanup on shutdown
    await session_manager.close_all()


app = FastAPI(
    title="Claude Code SDK Server",
    description="HTTP server exposing Claude Agent SDK capabilities",
    version="1.0.0",
    lifespan=lifespan
)


# ============================================================================
# Request/Response Models
# ============================================================================

class QueryRequest(BaseModel):
    """Request model for one-shot queries."""
    prompt: str = Field(..., description="The prompt to send to Claude")
    system_prompt: str | None = Field(None, description="Optional system prompt")
    max_turns: int | None = Field(None, description="Maximum conversation turns")
    allowed_tools: list[str] = Field(
        default_factory=lambda: ["Read", "Grep", "Glob"],
        description="List of allowed tool names"
    )
    permission_mode: str | None = Field(
        None,
        description="Permission mode: default, acceptEdits, plan, bypassPermissions"
    )
    cwd: str | None = Field(None, description="Working directory for the agent")
    include_custom_tools: bool = Field(
        True,
        description="Include server's custom tools (calculate, get_server_time)"
    )
    skills: list[str] = Field(
        default_factory=list,
        description="List of skill names to enable (e.g., ['pdf-processor', 'code-review'])"
    )
    setting_sources: list[str] = Field(
        default_factory=list,
        description="Setting sources for skill loading: ['user', 'project']"
    )
    output_format: dict[str, Any] | None = Field(
        None,
        description="Structured output format configuration with 'type' and 'schema' fields"
    )


class QueryResponse(BaseModel):
    """Response model for queries."""
    result: str | None = Field(None, description="Final result text")
    session_id: str = Field(..., description="Session ID for resumption")
    is_error: bool = Field(False, description="Whether the query resulted in an error")
    total_cost_usd: float | None = Field(None, description="Total cost in USD")
    duration_ms: int | None = Field(None, description="Duration in milliseconds")
    structured_output: dict[str, Any] | None = Field(
        None,
        description="Validated structured output matching the provided JSON schema"
    )
    subtype: str | None = Field(
        None,
        description="Result subtype: 'success', 'error_max_structured_output_retries', etc."
    )


class SessionRequest(BaseModel):
    """Request model for creating sessions."""
    system_prompt: str | None = Field(None, description="Optional system prompt")
    allowed_tools: list[str] = Field(
        default_factory=lambda: ["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
        description="List of allowed tool names"
    )
    permission_mode: str = Field(
        "acceptEdits",
        description="Permission mode for the session"
    )
    cwd: str | None = Field(None, description="Working directory")
    include_custom_tools: bool = Field(True, description="Include custom tools")
    skills: list[str] = Field(
        default_factory=list,
        description="List of skill names to enable (e.g., ['pdf-processor', 'code-review'])"
    )
    setting_sources: list[str] = Field(
        default_factory=list,
        description="Setting sources for skill loading: ['user', 'project']"
    )
    output_format: dict[str, Any] | None = Field(
        None,
        description="Structured output format configuration with 'type' and 'schema' fields"
    )


class SessionResponse(BaseModel):
    """Response model for session operations."""
    session_id: str
    status: str


class ChatRequest(BaseModel):
    """Request model for chat messages."""
    message: str = Field(..., description="Message to send")


class ChatResponse(BaseModel):
    """Response model for chat messages."""
    response: str
    is_complete: bool = True
    structured_output: dict[str, Any] | None = Field(
        None,
        description="Validated structured output if output_format was configured in session"
    )
    subtype: str | None = Field(
        None,
        description="Result subtype for structured output validation status"
    )


class MessageContent(BaseModel):
    """Model for message content in streaming."""
    type: str
    text: str | None = None
    tool_name: str | None = None
    tool_input: dict | None = None


class SkillInfo(BaseModel):
    """Information about an available skill."""
    name: str = Field(..., description="Skill name (directory name)")
    description: str | None = Field(None, description="Skill description from frontmatter")
    location: str = Field(..., description="'user' or 'project'")
    path: str = Field(..., description="Full path to SKILL.md")


class SkillsListResponse(BaseModel):
    """Response for listing available skills."""
    skills: list[SkillInfo] = Field(default_factory=list)
    count: int = Field(0, description="Total number of skills found")
    cwd: str | None = Field(None, description="Working directory used for project skills")


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
async def list_skills(cwd: str = Query(..., description="Working directory for project skills")):
    """
    List available skills from user and project directories.

    Skills are discovered from:
    - User: ~/.claude/skills/*/SKILL.md
    - Project: {cwd}/.claude/skills/*/SKILL.md (requires cwd)
    """
    from pathlib import Path

    skills = []

    # User skills (~/.claude/skills/)
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

    # Project skills ({cwd}/.claude/skills/)
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
async def single_query(request: QueryRequest):
    """
    Execute a one-shot query to Claude.

    This creates a new session for each request and returns the final result.
    Good for stateless, one-off tasks.
    """
    import traceback

    # Validate output_format if provided
    validate_output_format(request.output_format)

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
        cwd=request.cwd,
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

    try:
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


@app.post("/query/stream")
async def stream_query(request: QueryRequest):
    """
    Execute a streaming query to Claude.

    Returns a stream of server-sent events (SSE) with real-time responses.
    """
    # Validate output_format if provided
    validate_output_format(request.output_format)

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
        cwd=request.cwd,
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

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.post("/sessions", response_model=SessionResponse)
async def create_session(request: SessionRequest):
    """
    Create a new persistent session.

    Sessions maintain conversation context across multiple messages.
    """
    # Validate output_format if provided
    validate_output_format(request.output_format)

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
        cwd=request.cwd,
        mcp_servers=mcp_servers if mcp_servers else None,
        setting_sources=setting_sources,
        output_format=request.output_format
    )

    try:
        session_id = await session_manager.create_session(options=options)
        return SessionResponse(session_id=session_id, status="created")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/sessions/{session_id}", response_model=SessionResponse)
async def delete_session(session_id: str):
    """Close and delete a session."""
    try:
        await session_manager.close_session(session_id)
        return SessionResponse(session_id=session_id, status="deleted")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sessions/{session_id}/chat", response_model=ChatResponse)
async def chat(session_id: str, request: ChatRequest):
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
async def chat_stream(session_id: str, request: ChatRequest):
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
async def interrupt_session(session_id: str):
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
async def list_sessions():
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
    
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=port,
        reload=False
    )
