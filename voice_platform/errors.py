"""
Voice Platform — Centralized Error System
==========================================

Provides structured, user-friendly exceptions with:
  • Machine-readable error codes (for frontend i18n / analytics)
  • Human-readable messages (shown to users)
  • Actionable suggestions (what to do next)
  • HTTP status mapping (for REST responses)

Usage in routes:
    from voice_platform.errors import NotFoundError, ValidationError

    if not agent:
        raise NotFoundError(
            resource="Agent",
            resource_id=agent_id,
            suggestion="Check the agent ID or create a new agent."
        )

    if duration < 0:
        raise ValidationError(
            field="duration",
            message="Duration must be a positive number.",
            suggestion="Use a value greater than 0."
        )

The global exception handler in main.py converts these into JSON:
    {
        "error": {
            "code": "AGENT_NOT_FOUND",
            "message": "Agent #42 was not found.",
            "detail": {...},
            "suggestion": "Check the agent ID or create a new agent."
        }
    }
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from fastapi import HTTPException, status

# ═══════════════════════════════════════════════════════════════════════
# Error Codes — stable identifiers for frontend + analytics
# ═══════════════════════════════════════════════════════════════════════

class ErrorCode(str, Enum):
    """Machine-readable error codes.  Never change existing values."""

    # Auth
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    SESSION_EXPIRED = "SESSION_EXPIRED"

    # Validation
    VALIDATION_ERROR = "VALIDATION_ERROR"
    MISSING_FIELD = "MISSING_FIELD"
    INVALID_FIELD = "INVALID_FIELD"

    # Resources
    NOT_FOUND = "NOT_FOUND"
    ALREADY_EXISTS = "ALREADY_EXISTS"

    # Agents
    AGENT_NOT_FOUND = "AGENT_NOT_FOUND"
    AGENT_INACTIVE = "AGENT_INACTIVE"
    AGENT_NO_PHONE = "AGENT_NO_PHONE"

    # Calls
    CALL_NOT_FOUND = "CALL_NOT_FOUND"
    CALL_FAILED = "CALL_FAILED"
    CALL_SCHEDULE_FAILED = "CALL_SCHEDULE_FAILED"
    CALL_THROTTLED = "CALL_THROTTLED"

    # Telephony
    TWILIO_ERROR = "TWILIO_ERROR"
    TWILIO_NOT_CONFIGURED = "TWILIO_NOT_CONFIGURED"

    # Workflows
    WORKFLOW_NOT_FOUND = "WORKFLOW_NOT_FOUND"
    WORKFLOW_EXECUTION_ERROR = "WORKFLOW_EXECUTION_ERROR"
    WORKFLOW_INVALID_GRAPH = "WORKFLOW_INVALID_GRAPH"

    # Integrations
    INTEGRATION_NOT_FOUND = "INTEGRATION_NOT_FOUND"
    INTEGRATION_ERROR = "INTEGRATION_ERROR"
    MCP_SERVER_ERROR = "MCP_SERVER_ERROR"
    MCP_TOOL_NOT_FOUND = "MCP_TOOL_NOT_FOUND"

    # Knowledge Base
    KB_NOT_FOUND = "KB_NOT_FOUND"
    KB_SEARCH_ERROR = "KB_SEARCH_ERROR"

    # Database
    DB_ERROR = "DB_ERROR"
    DB_CONFLICT = "DB_CONFLICT"

    # External APIs
    LLM_ERROR = "LLM_ERROR"
    STT_ERROR = "STT_ERROR"
    TTS_ERROR = "TTS_ERROR"

    # Rate limiting
    RATE_LIMITED = "RATE_LIMITED"

    # Generic
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


# ═══════════════════════════════════════════════════════════════════════
# Base AppError
# ═══════════════════════════════════════════════════════════════════════

class AppError(Exception):
    """
    Base exception for all application-level errors.

    Fields:
        code:        Machine-readable error code.
        message:     Human-readable description (shown to user).
        status_code: HTTP status to return.
        detail:      Extra context (safe for external exposure).
        suggestion:  Actionable advice for the user.
    """

    def __init__(
        self,
        *,
        code: ErrorCode = ErrorCode.INTERNAL_ERROR,
        message: str = "An unexpected error occurred.",
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail: Optional[Dict[str, Any]] = None,
        suggestion: Optional[str] = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail or {}
        self.suggestion = suggestion
        super().__init__(message)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to the public JSON error format."""
        payload: Dict[str, Any] = {
            "code": self.code.value,
            "message": self.message,
        }
        if self.detail:
            payload["detail"] = self.detail
        if self.suggestion:
            payload["suggestion"] = self.suggestion
        return payload

    def to_http_exception(self) -> HTTPException:
        """Convert to a FastAPI HTTPException for use in routes."""
        return HTTPException(
            status_code=self.status_code,
            detail={"error": self.to_dict()},
        )


# ═══════════════════════════════════════════════════════════════════════
# Concrete Error Classes
# ═══════════════════════════════════════════════════════════════════════

class AuthError(AppError):
    """Base for all authentication / authorization errors."""
    code: ErrorCode = ErrorCode.UNAUTHORIZED
    status_code: int = status.HTTP_401_UNAUTHORIZED


class ForbiddenError(AppError):
    code: ErrorCode = ErrorCode.FORBIDDEN
    message: str = "You don't have permission to perform this action."
    status_code: int = status.HTTP_403_FORBIDDEN


class ValidationError(AppError):
    """Input validation failure."""
    code: ErrorCode = ErrorCode.VALIDATION_ERROR
    status_code: int = status.HTTP_422_UNPROCESSABLE_ENTITY

    def __init__(
        self,
        *,
        field: Optional[str] = None,
        message: str = "Invalid input.",
        suggestion: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            code=ErrorCode.VALIDATION_ERROR,
            message=message,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail or {},
            suggestion=suggestion,
        )
        if field:
            self.detail["field"] = field


class NotFoundError(AppError):
    """Generic resource-not-found error."""
    code: ErrorCode = ErrorCode.NOT_FOUND
    status_code: int = status.HTTP_404_NOT_FOUND

    def __init__(
        self,
        *,
        resource: str = "Resource",
        resource_id: Optional[Any] = None,
        code: Optional[ErrorCode] = None,
        message: Optional[str] = None,
        suggestion: Optional[str] = None,
    ):
        msg = message or (
            f"{resource} {f'#{resource_id} ' if resource_id else ''}was not found."
        )
        detail: Dict[str, Any] = {"resource": resource}
        if resource_id is not None:
            detail["id"] = resource_id
        resolved_code = code or getattr(ErrorCode, f"{resource.upper()}_NOT_FOUND", None) or ErrorCode.NOT_FOUND
        super().__init__(
            code=resolved_code,
            message=msg,
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail,
            suggestion=suggestion or f"Check the {resource.lower()} ID or create a new one.",
        )


class AlreadyExistsError(AppError):
    code: ErrorCode = ErrorCode.ALREADY_EXISTS
    status_code: int = status.HTTP_409_CONFLICT

    def __init__(
        self,
        *,
        resource: str = "Resource",
        identifier: Optional[str] = None,
        message: Optional[str] = None,
        suggestion: Optional[str] = None,
    ):
        msg = message or (
            f"{resource} '{identifier}' already exists." if identifier
            else f"{resource} already exists."
        )
        detail: Dict[str, Any] = {"resource": resource}
        if identifier:
            detail["identifier"] = identifier
        super().__init__(
            code=ErrorCode.ALREADY_EXISTS,
            message=msg,
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
            suggestion=suggestion or "Use a different name or update the existing item.",
        )


class AgentNotFoundError(NotFoundError):
    def __init__(self, agent_id: Any, suggestion: Optional[str] = None):
        super().__init__(
            resource="Agent",
            resource_id=agent_id,
            code=ErrorCode.AGENT_NOT_FOUND,
            message=f"Agent #{agent_id} was not found.",
            suggestion=suggestion or "Check the agent ID or create a new agent.",
        )


class AgentInactiveError(AppError):
    code: ErrorCode = ErrorCode.AGENT_INACTIVE
    status_code: int = status.HTTP_400_BAD_REQUEST

    def __init__(self, agent_id: Any, suggestion: Optional[str] = None):
        super().__init__(
            code=ErrorCode.AGENT_INACTIVE,
            message=f"Agent #{agent_id} is currently inactive.",
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"agent_id": agent_id},
            suggestion=suggestion or "Activate the agent in Settings before making calls.",
        )


class CallFailedError(AppError):
    code: ErrorCode = ErrorCode.CALL_FAILED
    status_code: int = status.HTTP_502_BAD_GATEWAY

    def __init__(self, reason: str, suggestion: Optional[str] = None):
        super().__init__(
            code=ErrorCode.CALL_FAILED,
            message=f"The call could not be completed: {reason}",
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"reason": reason},
            suggestion=suggestion or "Check your telephony configuration and try again.",
        )


class TwilioNotConfiguredError(AppError):
    code: ErrorCode = ErrorCode.TWILIO_NOT_CONFIGURED
    status_code: int = status.HTTP_503_SERVICE_UNAVAILABLE

    def __init__(self):
        super().__init__(
            code=ErrorCode.TWILIO_NOT_CONFIGURED,
            message="Twilio is not configured.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            suggestion="Add TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN to your .env file.",
        )


class IntegrationNotFoundError(NotFoundError):
    def __init__(self, integration_id: Any, suggestion: Optional[str] = None):
        super().__init__(
            resource="Integration",
            resource_id=integration_id,
            code=ErrorCode.INTEGRATION_NOT_FOUND,
            message=f"Integration #{integration_id} was not found.",
            suggestion=suggestion or "Connect the integration first under Settings > Integrations.",
        )


class IntegrationError(AppError):
    code: ErrorCode = ErrorCode.INTEGRATION_ERROR
    status_code: int = status.HTTP_502_BAD_GATEWAY

    def __init__(self, service: str, reason: str, suggestion: Optional[str] = None):
        super().__init__(
            code=ErrorCode.INTEGRATION_ERROR,
            message=f"{service} integration error: {reason}",
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"service": service, "reason": reason},
            suggestion=suggestion or f"Check your {service} credentials and try again.",
        )


class McpServerError(AppError):
    code: ErrorCode = ErrorCode.MCP_SERVER_ERROR
    status_code: int = status.HTTP_502_BAD_GATEWAY

    def __init__(self, server_url: str, reason: str, suggestion: Optional[str] = None):
        super().__init__(
            code=ErrorCode.MCP_SERVER_ERROR,
            message=f"MCP server at {server_url} returned an error: {reason}",
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"server_url": server_url, "reason": reason},
            suggestion=suggestion or "Verify the MCP server URL and that it is reachable.",
        )


class WorkflowNotFoundError(NotFoundError):
    def __init__(self, workflow_id: Any, suggestion: Optional[str] = None):
        super().__init__(
            resource="Workflow",
            resource_id=workflow_id,
            code=ErrorCode.WORKFLOW_NOT_FOUND,
            message=f"Workflow #{workflow_id} was not found.",
            suggestion=suggestion or "Check the workflow ID or create a new workflow.",
        )


class WorkflowError(AppError):
    """Generic workflow-level error (used by review queue and graph executor)."""
    code: ErrorCode = ErrorCode.WORKFLOW_EXECUTION_ERROR
    status_code: int = status.HTTP_400_BAD_REQUEST

    def __init__(self, message: str = "Workflow error.", suggestion: Optional[str] = None):
        super().__init__(
            code=ErrorCode.WORKFLOW_EXECUTION_ERROR,
            message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
            suggestion=suggestion or "Review the workflow configuration.",
        )


class WorkflowExecutionError(AppError):
    code: ErrorCode = ErrorCode.WORKFLOW_EXECUTION_ERROR
    status_code: int = status.HTTP_400_BAD_REQUEST

    def __init__(self, workflow_id: Any, reason: str, suggestion: Optional[str] = None):
        super().__init__(
            code=ErrorCode.WORKFLOW_EXECUTION_ERROR,
            message=f"Workflow #{workflow_id} failed to execute: {reason}",
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"workflow_id": workflow_id, "reason": reason},
            suggestion=suggestion or "Review the workflow steps and try again.",
        )


class KnowledgeBaseNotFoundError(NotFoundError):
    def __init__(self, kb_id: Any, suggestion: Optional[str] = None):
        super().__init__(
            resource="Knowledge Base",
            resource_id=kb_id,
            code=ErrorCode.KB_NOT_FOUND,
            message=f"Knowledge base #{kb_id} was not found.",
            suggestion=suggestion or "Upload documents to create a knowledge base.",
        )


class DatabaseError(AppError):
    code: ErrorCode = ErrorCode.DB_ERROR
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(self, message: str = "A database error occurred.", suggestion: Optional[str] = None):
        super().__init__(
            code=ErrorCode.DB_ERROR,
            message=message,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            suggestion=suggestion or "Please try again in a moment. If the problem persists, contact support.",
        )


class LLMError(AppError):
    code: ErrorCode = ErrorCode.LLM_ERROR
    status_code: int = status.HTTP_502_BAD_GATEWAY

    def __init__(self, provider: str, reason: str, suggestion: Optional[str] = None):
        super().__init__(
            code=ErrorCode.LLM_ERROR,
            message=f"{provider} LLM error: {reason}",
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"provider": provider, "reason": reason},
            suggestion=suggestion or "Check your API key and model settings, then try again.",
        )


class RateLimitedError(AppError):
    code: ErrorCode = ErrorCode.RATE_LIMITED
    status_code: int = status.HTTP_429_TOO_MANY_REQUESTS

    def __init__(self, retry_after: Optional[int] = None, suggestion: Optional[str] = None):
        detail: Dict[str, Any] = {}
        if retry_after:
            detail["retry_after_seconds"] = retry_after
        super().__init__(
            code=ErrorCode.RATE_LIMITED,
            message="Too many requests. Please slow down.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
            suggestion=suggestion or "Wait a moment before trying again.",
        )


class ServiceUnavailableError(AppError):
    code: ErrorCode = ErrorCode.SERVICE_UNAVAILABLE
    status_code: int = status.HTTP_503_SERVICE_UNAVAILABLE

    def __init__(self, service: str, suggestion: Optional[str] = None):
        super().__init__(
            code=ErrorCode.SERVICE_UNAVAILABLE,
            message=f"{service} is temporarily unavailable.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"service": service},
            suggestion=suggestion or "Please try again in a few moments.",
        )
