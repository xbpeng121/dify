SYSTEM_VARIABLE_NODE_ID = "sys"
ENVIRONMENT_VARIABLE_NODE_ID = "env"
CONVERSATION_VARIABLE_NODE_ID = "conversation"

from core.variables.types import SegmentType
from core.workflow.enums import SystemVariableKey
from core.workflow.nodes import NodeType

VARIABLE_TYPES = {
    f"{SYSTEM_VARIABLE_NODE_ID}.{SystemVariableKey.QUERY}": SegmentType.STRING,
    f"{SYSTEM_VARIABLE_NODE_ID}.{SystemVariableKey.FILES}": SegmentType.ARRAY_FILE,
    f"{SYSTEM_VARIABLE_NODE_ID}.{SystemVariableKey.CONVERSATION_ID}": SegmentType.STRING,
    f"{SYSTEM_VARIABLE_NODE_ID}.{SystemVariableKey.USER_ID}": SegmentType.STRING,
    f"{SYSTEM_VARIABLE_NODE_ID}.{SystemVariableKey.DIALOGUE_COUNT}":  SegmentType.NUMBER,
    f"{SYSTEM_VARIABLE_NODE_ID}.{SystemVariableKey.APP_ID}": SegmentType.STRING,
    f"{SYSTEM_VARIABLE_NODE_ID}.{SystemVariableKey.WORKFLOW_ID}": SegmentType.STRING,
    f"{SYSTEM_VARIABLE_NODE_ID}.{SystemVariableKey.WORKFLOW_RUN_ID}": SegmentType.STRING,

    # f"{NodeType.START}.": SegmentType.STRING,
    # f"{NodeType.END}.": SegmentType.STRING,
    # f"{NodeType.ANSWER}.": SegmentType.STRING,
    f"{NodeType.LLM}.text": SegmentType.STRING,
    f"{NodeType.KNOWLEDGE_RETRIEVAL}.result": SegmentType.ARRAY_OBJECT,
    # f"{NodeType.IF_ELSE}.": SegmentType.STRING,
    f"{NodeType.CODE}.output": SegmentType.OBJECT,
    f"{NodeType.TEMPLATE_TRANSFORM}.output": SegmentType.STRING,
    f"{NodeType.QUESTION_CLASSIFIER}.class_name": SegmentType.STRING,
    f"{NodeType.HTTP_REQUEST}.body": SegmentType.STRING,
    f"{NodeType.HTTP_REQUEST}.status_code": SegmentType.NUMBER,
    f"{NodeType.TOOL}.text": SegmentType.STRING,
    f"{NodeType.TOOL}.files": SegmentType.ARRAY_FILE,
    f"{NodeType.VARIABLE_AGGREGATOR}.output": SegmentType.STRING,
    # f"{NodeType.LEGACY_VARIABLE_AGGREGATOR}.": SegmentType.STRING,
    # f"{NodeType.LOOP}.": SegmentType.STRING,
    f"{NodeType.LOOP_START}.output": SegmentType.STRING,
    # f"{NodeType.ITERATION}.": SegmentType.STRING,
    # f"{NodeType.ITERATION_START}.": SegmentType.STRING,
    # f"{NodeType.PARAMETER_EXTRACTOR}.": SegmentType.STRING,
    # f"{NodeType.VARIABLE_ASSIGNER}.": SegmentType.STRING,
    f"{NodeType.DOCUMENT_EXTRACTOR}.text": SegmentType.STRING,
    # f"{NodeType.LIST_OPERATOR}.": SegmentType.STRING,
    # f"{NodeType.AGENT}.": SegmentType.STRING,
}


 