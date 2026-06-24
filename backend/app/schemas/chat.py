from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


WorkflowIntent = Literal[
    "report_parsing",
    "profile_analysis",
    "health_risk",
    "recipe_generation",
    "meal_record",
    "diet_history_analysis",
    "recommendation",
    "nutrition_analysis",
]


class UserProfileData(BaseModel):
    """用户画像上下文。"""

    medical_report_markdown: str = ""


class HealthRiskData(BaseModel):
    """健康风险评估结果。"""

    level: str = "unknown"
    warnings: list[str] = Field(default_factory=list)
    forbidden_foods: list[str] = Field(default_factory=list)
    focus_diseases: list[str] = Field(default_factory=list)


class NutritionAnalysisData(BaseModel):
    """营养分析结果。"""

    calories_kcal: int = 1800
    protein_g: int = 90
    carbohydrate_g: int = 200
    fat_g: int = 55
    dietary_fiber_g: int = 28
    sodium_mg: int = 1800
    sugar_g: int = 25
    vitamin_focus: list[str] = Field(default_factory=list)
    trace_elements: list[str] = Field(default_factory=list)


class RecipeMealItem(BaseModel):
    """单个餐次食谱项。"""

    day_label: str | None = None
    meal_type: Literal["早餐", "午餐", "晚餐", "加餐"]
    dish_name: str
    ingredients: list[str] = Field(default_factory=list)
    weight: str
    calories_kcal: int
    nutrition_analysis: str
    cooking_method: str


class MealConsumedItem(BaseModel):
    """识别出的实际进食食物。"""

    food_name: str
    weight_estimate: str
    estimated_grams: int


class MicronutrientEstimate(BaseModel):
    """本次进食的微量元素估算。"""

    name: str
    amount: float
    unit: str


class MealRecordData(BaseModel):
    """用餐记录。"""

    recorded_at: datetime
    meal_type: str
    foods: list[str] = Field(default_factory=list)
    consumed_items: list[MealConsumedItem] = Field(default_factory=list)
    micronutrients: list[MicronutrientEstimate] = Field(default_factory=list)
    estimated_calories_kcal: int | None = None
    estimated_protein_g: float | None = None
    estimated_carbohydrate_g: float | None = None
    estimated_fat_g: float | None = None
    estimated_dietary_fiber_g: float | None = None
    estimated_sodium_mg: float | None = None
    analysis_markdown: str | None = None
    feedback: str | None = None


class AgentTraceStep(BaseModel):
    """工作流中的 Agent 执行轨迹。"""

    agent_name: str
    summary: str
    created_at: datetime


class AgentRouteDecision(BaseModel):
    """主控 Agent 的路由决策。"""

    intent: WorkflowIntent
    target_agent: str
    reason: str = ""
    source: str = "llm"


class ConversationMemoryItem(BaseModel):
    """用于 Agent 的轻量对话记忆。"""

    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class WorkflowState(BaseModel):
    """多 Agent 统一状态。"""

    has_medical_report: bool = False  # 当前会话是否已经拥有可用的体检报告 Markdown。
    profile_completed: bool = False  # 是否已经基于体检报告完成用户画像上下文初始化。
    health_risk_level: str = "unknown"  # 当前健康风险等级，默认 unknown。
    goal: str = ""  # 用户主动表达的饮食、控糖、减脂等目标。
    diet_preference: list[str] = Field(default_factory=list)  # 用户饮食偏好，例如清淡、少油、偏素等。
    allergy: list[str] = Field(default_factory=list)  # 用户过敏或明确需要规避的食物。
    disease: list[str] = Field(default_factory=list)  # 从报告或对话中识别出的重点疾病/健康问题。
    medical_report: str | None = None  # 体检报告解析 agent 生成的全局共享 Markdown 正文。
    user_profile: UserProfileData | None = None  # 用户画像上下文，目前主要保存体检报告 Markdown。
    health_risk: HealthRiskData | None = None  # 健康风险评估 agent 的结构化结果。
    nutrition_analysis: NutritionAnalysisData | None = None  # 营养分析 agent 生成的每日营养目标。
    recipe_plan: list[RecipeMealItem] = Field(default_factory=list)  # 规则型食谱数据列表，大模型 Markdown 食谱不一定写入这里。
    recommendations: list[str] = Field(default_factory=list)  # 饮食建议 agent 生成的建议列表。
    meal_records: list[MealRecordData] = Field(default_factory=list)  # 当前会话内新增的用餐记录。
    latest_guard_message: str = "为了生成更加准确、安全、个性化的饮食方案，请先上传最近的体检报告。"  # 守卫 agent 最近一次拦截提示。
    latest_profile_reply: str = ""  # 用户画像 agent 最近一次生成的 Markdown 展示结果。
    latest_health_risk_reply: str = ""  # 健康风险/忌口 agent 最近一次生成的 Markdown 展示结果。
    latest_recipe_reply: str = ""  # 食谱生成 agent 最近一次生成的 Markdown 食谱结果。
    last_route: AgentRouteDecision | None = None  # 主控 agent 最近一次路由决策。
    agent_trace: list[AgentTraceStep] = Field(default_factory=list)  # 本轮或当前会话内的 agent 执行轨迹。
    recent_history: list[ConversationMemoryItem] = Field(default_factory=list)  # 提供给 agent 的轻量最近对话上下文。


class ChatMessage(BaseModel):
    """单条聊天消息。"""

    id: str
    role: Literal["user", "assistant"]
    content: str
    thinking_content: str = ""
    created_at: datetime
    suggested_questions: list[str] = Field(default_factory=list)


class ChatSessionSummary(BaseModel):
    """会话列表摘要。"""

    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    last_message_preview: str | None = None
    has_medical_report: bool = False
    health_risk_level: str = "unknown"


class ChatSessionDetail(ChatSessionSummary):
    """会话详情，包含完整消息列表。"""

    messages: list[ChatMessage] = Field(default_factory=list)
    workflow_state: WorkflowState = Field(default_factory=WorkflowState)


class CreateChatSessionRequest(BaseModel):
    """创建会话请求。"""

    title: str | None = Field(default=None, max_length=50)


class SendMessageRequest(BaseModel):
    """发送消息请求。"""

    content: str = Field(min_length=1, max_length=2000)


class UploadMedicalReportRequest(BaseModel):
    """直接提交体检报告文本。"""

    report_text: str = Field(min_length=1)
