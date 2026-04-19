import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class TemplateVariableSchema(BaseModel):
    id: uuid.UUID
    key: str
    label: str
    type: str
    default_value: Optional[Dict[str, Any]] = None
    validation_rules: Optional[Dict[str, Any]] = None
    is_required: bool
    is_secret: bool

    class Config:
        from_attributes = True


class TemplatePlaybookSchema(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    trigger_condition: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class TemplateToolSchema(BaseModel):
    id: uuid.UUID
    tool_name: str
    required_config_schema: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class TemplateVersionSchema(BaseModel):
    id: uuid.UUID
    version: int
    system_prompt_template: Optional[str] = None
    orchestration_logic: Optional[Dict[str, Any]] = None
    playbooks: List[TemplatePlaybookSchema] = []
    tools: List[TemplateToolSchema] = []
    compliance: Optional[Dict[str, Any]] = None
    guardrails: Optional[Dict[str, Any]] = None
    emergency_protocols: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class AgentTemplateSchema(BaseModel):
    id: uuid.UUID
    key: str
    name: str
    description: Optional[str] = None
    category: str
    is_active: bool
    variables: List[TemplateVariableSchema] = []
    versions: List[TemplateVersionSchema] = []

    class Config:
        from_attributes = True


class TemplateInstantiationRequest(BaseModel):
    agent_id: str
    template_version_id: str
    variable_values: Dict[str, Any] = Field(default_factory=dict)
    tool_configs: Dict[str, Any] = Field(default_factory=dict)


class AgentTemplateInstanceSchema(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    agent_id: uuid.UUID
    template_version_id: uuid.UUID
    variable_values: Optional[Dict[str, Any]] = None
    tool_configs: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True
