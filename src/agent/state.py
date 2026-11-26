from typing import TypedDict, List, Dict, Any, Optional


from langchain_core.messages import BaseMessage





class AgentState(TypedDict, total=False):


    # =====================================
    # LangGraph Messages
    # =====================================

    messages: List[BaseMessage]



    # =====================================
    # 用户身份
    # =====================================

    user_id: str
    chat_session_id: Optional[str]





    # =====================================
    # 多轮历史
    # history_node 生成
    # =====================================

    history: List[Dict[str, Any]]





    # =====================================
    # 长期记忆
    # memory_node 生成
    # =====================================

    memory: List[Dict[str, Any]]





    # =====================================
    # Tool
    # =====================================

    need_tool: bool



    tool_called: bool



    tool_name: str



    plan: Optional[Dict[str, Any]]
    plan_error: str
    plan_index: int
    execution_records: List[Dict[str, Any]]
    execution_messages: List[BaseMessage]
    execution_error: str
    tool_calls: Optional[List[Dict[str, Any]]]

    tool_args: Dict[str, Any]



    tool_result: str





    # =====================================
    # Agent 输出
    # =====================================

    response: str
    citations: List[Dict[str, Any]]
    task: Dict[str, Any]
    document_calls: List[str]
    task_id: Optional[str]
    calendar: Optional[Dict[str, Any]]
    mode: str
    source_message_id: Optional[int]
    memory_notes: List[str]
    memory_outcomes: List[Dict[str, Any]]
    memory_generation: Optional[int]
    history_summary: Optional[Dict[str, Any]]



    step: str
