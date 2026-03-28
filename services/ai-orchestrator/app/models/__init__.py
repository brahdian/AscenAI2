# Import all ORM models so they register with Base.metadata
# and are auto-created by init_db() via create_all().
from app.models.agent import (  # noqa: F401
    Agent,
    AgentAnalytics,
    AgentDocument,
    AgentGuardrails,
    AgentPlaybook,
    Message,
    MessageFeedback,
    PlaybookExecution,
    Session,
)
from app.models.trace import ConversationTrace  # noqa: F401
from app.models.eval import EvalCase, EvalRun, EvalScore  # noqa: F401
from app.models.prompt import PromptVersion, PromptABTest  # noqa: F401
