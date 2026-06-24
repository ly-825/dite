from __future__ import annotations
import base64
from datetime import datetime
import json
import mimetypes
import os
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from io import BytesIO
from threading import local
from typing import Any, cast

from openai import OpenAI
from openai.types.chat import ChatCompletionSystemMessageParam, ChatCompletionUserMessageParam
from pypdf import PdfReader

from app.core.config import settings
from app.schemas.chat import (
    HealthRiskData,
    NutritionAnalysisData,
    RecipeMealItem,
    UserProfileData,
    WorkflowIntent,
    WorkflowState,
)


LLM_HISTORY_LIMIT = 6
THINKING_LANGUAGE_PROMPT = (
    "思考过程尽量使用中文思考，并且推理过程是面向大众普通用户，尽量不要使用英文推理。"
)
LLM_PAYLOAD_KEY_TRANSLATIONS = {
    "current_user_message": "当前用户输入",
    "recent_user_messages": "近期用户消息",
    "assistant_reply": "助手回复",
    "goal": "目标",
    "disease": "健康限制",
    "diet_preference": "饮食偏好",
    "allergy": "过敏信息",
    "latest_route": "最近路由",
    "user_message": "用户输入",
    "guard_agent": "守卫智能体",
    "candidate_agents": "候选智能体",
    "history_records": "历史用餐记录",
    "region": "地区",
    "season": "季节",
    "month": "月份",
    "time_of_day": "当前时段",
    "current_datetime": "当前日期时间",
    "intent": "意图",
    "target_agent": "目标智能体",
    "reason": "原因",
    "agent_name": "智能体名称",
    "responsibility": "职责",
    "always_runs": "是否总是执行",
    "selectable": "是否可被选择",
    "when_to_use": "使用场景",
    "depends_on": "依赖智能体",
    "nutrition_target": "营养目标",
    "nutrition": "营养分析",
    "recipes": "食谱列表",
    "recommendations": "推荐建议",
    "fallback_reply": "兜底回复",
    "recent_history": "近期对话",
    "recipe_filter_conditions": "食谱数据库筛选条件",
    "recipe_region_priority": "食谱地区优先级",
    "recipe_database_candidates": "食谱数据库候选",
    "candidate_meal_plan": "候选餐次计划",
    "_region_priority": "地区优先级",
    "specific_regions": "具体地区",
    "usage_rule": "使用规则",
    "breakfast": "早餐类",
    "staple": "主食类",
    "soup": "汤类",
    "vegetable": "素菜类",
    "meat": "荤菜类",
    "aquatic": "水产类",
    "name": "菜品名称",
    "category": "分类",
    "ingredients": "食材",
    "ingredient_categories": "食材分类",
    "people_type": "人群类型",
    "avoid_people": "规避人群",
    "calories": "热量",
    "protein": "蛋白质",
    "carbohydrate": "碳水化合物",
    "fat": "脂肪",
    "calories_kcal": "热量千卡",
    "protein_g": "蛋白质克数",
    "carbohydrate_g": "碳水化合物克数",
    "fat_g": "脂肪克数",
    "dietary_fiber_g": "膳食纤维克数",
    "sodium_mg": "钠毫克数",
    "sugar_g": "糖克数",
    "vitamin_focus": "重点维生素",
    "trace_elements": "微量元素",
    "meal_type": "餐次",
    "dish_name": "菜品名称",
    "weight": "重量",
    "nutrition_analysis": "营养分析",
    "cooking_method": "供餐说明",
    "day_label": "日期标签",
    "role": "角色",
    "content": "内容",
    "created_at": "创建时间",
    "recorded_at": "记录时间",
    "analysis_markdown": "分析正文",
}
RECIPE_CATEGORY_TABLE_CANDIDATES = {
    "soup": ["soup_porridge", "soups", "soup", "recipe_soup", "recipe_soups", "soup_dishes", "tang", "汤类", "汤品"],
    "staple": ["staple_food", "staples", "staple_foods", "recipe_staple", "recipe_staples", "main_foods", "zhushi", "主食类", "主食"],
    "vegetable": ["vegetable_dish", "vegetables", "vegetable_dishes", "recipe_vegetable", "recipe_vegetables", "sucai", "素菜类", "素菜"],
    "meat": ["meat_dish", "meats", "meat_dishes", "recipe_meat", "recipe_meats", "huncai", "荤菜类", "荤菜"],
    "aquatic": ["aquatic_dish", "aquatics", "aquatic_dishes", "recipe_aquatic", "recipe_aquatics", "shuichan", "水产类", "水产"],
    "breakfast": ["breakfast_snack", "breakfasts", "breakfast_foods", "recipe_breakfast", "recipe_breakfasts", "zaocan", "早餐类", "早餐"],
}


class DashScopeLLMService:
    """DashScope/OpenAI-compatible wrapper."""

    def __init__(self) -> None:
        self.enabled = bool(settings.dashscope_api_key)
        self.client: OpenAI | None = None
        self._thinking_context = local()
        if self.enabled:
            self.client = OpenAI(
                api_key=settings.dashscope_api_key,
                base_url=settings.llm_base_url,
                timeout=settings.llm_timeout_seconds,
            )
            prompt = (
                "你会看到同一份餐食的餐前图和餐后图，请对比后输出一份 markdown 格式的用餐分析。"
                "重点说明实际吃掉了哪些食物、每种食物大致吃掉多少、整体摄入情况和简要营养点评。"
                "直接返回 markdown 正文，不要返回 JSON，不要写代码块。"
                "请使用以下结构：\n"
                "## 本次用餐分析\n"
                "### 实际吃掉的食物\n"
                "- 米饭：约120g\n"
                "- 鸡胸肉：约80g\n"
                "### 营养概览\n"
                "- 热量：约520 kcal\n"
                "- 蛋白质：约28 g\n"
                "- 碳水化合物：约56 g\n"
                "- 脂肪：约18 g\n"
                "### 简要点评\n"
                "- 这餐蛋白质较充足，蔬菜偏少。\n"
            )

    @contextmanager
    def thinking_stream(self, callback: Callable[[str], None]) -> Iterator[None]:
        previous_callback = getattr(self._thinking_context, "callback", None)
        self._thinking_context.callback = callback
        try:
            yield
        finally:
            self._thinking_context.callback = previous_callback

    @contextmanager
    def stream_callbacks(
        self,
        *,
        thinking_callback: Callable[[str], None],
        answer_callback: Callable[[str], None],
    ) -> Iterator[None]:
        previous_thinking_callback = getattr(self._thinking_context, "callback", None)
        previous_answer_callback = getattr(self._thinking_context, "answer_callback", None)
        self._thinking_context.callback = thinking_callback
        self._thinking_context.answer_callback = answer_callback
        try:
            yield
        finally:
            self._thinking_context.callback = previous_thinking_callback
            self._thinking_context.answer_callback = previous_answer_callback

    @contextmanager
    def _suppress_stream_callbacks(self) -> Iterator[None]:
        previous_thinking_callback = getattr(self._thinking_context, "callback", None)
        previous_answer_callback = getattr(self._thinking_context, "answer_callback", None)
        self._thinking_context.callback = None
        self._thinking_context.answer_callback = None
        try:
            yield
        finally:
            self._thinking_context.callback = previous_thinking_callback
            self._thinking_context.answer_callback = previous_answer_callback

    def _active_thinking_callback(self) -> Callable[[str], None] | None:
        callback = getattr(self._thinking_context, "callback", None)
        return callback if callable(callback) else None

    def _active_answer_callback(self) -> Callable[[str], None] | None:
        callback = getattr(self._thinking_context, "answer_callback", None)
        return callback if callable(callback) else None

    def _emit_thinking_text(self, content: str) -> None:
        # thinking 流只承载大模型返回的 reasoning_content，不承载系统进度文案。
        return

    def _complete_chat_with_optional_thinking(
        self,
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        messages: list[ChatCompletionSystemMessageParam | ChatCompletionUserMessageParam],
        stream_answer: bool = False,
    ) -> str:
        if self.client is None:
            return ""

        messages = self._prepend_thinking_language_prompt(messages)
        thinking_callback = self._active_thinking_callback()
        answer_callback = self._active_answer_callback() if stream_answer else None
        if thinking_callback is None and answer_callback is None:
            response = self.client.chat.completions.create(
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=messages,
                extra_body={"enable_thinking": True},
            )
            print("正在思考")
            return response.choices[0].message.content if response.choices else ""

        content_parts: list[str] = []
        stream = self.client.chat.completions.create(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=messages,
            stream=True,
            extra_body={"enable_thinking": True},
        )
        for chunk in stream:
            for event_type, event_content in self._iter_chat_stream_events(chunk):
                if event_type == "thinking":
                    if thinking_callback:
                        thinking_callback(event_content)
                else:
                    if answer_callback:
                        answer_callback(event_content)
                    content_parts.append(event_content)
        return "".join(content_parts)

    def _prepend_thinking_language_prompt(
        self,
        messages: list[ChatCompletionSystemMessageParam | ChatCompletionUserMessageParam],
    ) -> list[ChatCompletionSystemMessageParam | ChatCompletionUserMessageParam]:
        return [
            cast(ChatCompletionSystemMessageParam, {"role": "system", "content": THINKING_LANGUAGE_PROMPT}),
            *messages,
        ]

    def _stream_chat_with_thinking(
        self,
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        messages: list[ChatCompletionSystemMessageParam | ChatCompletionUserMessageParam],
    ):
        if self.client is None:
            return

        messages = self._prepend_thinking_language_prompt(messages)
        stream = self.client.chat.completions.create(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=messages,
            stream=True,
            extra_body={"enable_thinking": True},
        )
        for chunk in stream:
            for event_type, event_content in self._iter_chat_stream_events(chunk):
                yield {"type": event_type, "content": event_content}

    def _iter_chat_stream_events(self, chunk: Any):
        choices = getattr(chunk, "choices", None)
        if not choices and isinstance(chunk, dict):
            choices = chunk.get("choices")
        if not choices:
            return

        choice = choices[0]
        delta = getattr(choice, "delta", None)
        if delta is None and isinstance(choice, dict):
            delta = choice.get("delta")
        if delta is None:
            return

        thinking_delta = self._extract_delta_value(delta, "reasoning_content")
        if thinking_delta:
            yield "thinking", thinking_delta

        answer_delta = self._extract_delta_value(delta, "content")
        if answer_delta:
            yield "answer", answer_delta

    def _extract_delta_value(self, delta: Any, key: str) -> str:
        value = getattr(delta, key, None)
        if value is None and isinstance(delta, dict):
            value = delta.get(key)
        if value is None:
            model_extra = getattr(delta, "model_extra", None)
            if isinstance(model_extra, dict):
                value = model_extra.get(key)
        return str(value or "")

    def _dump_llm_payload(self, payload: Any, *, indent: int | None = None) -> str:
        return json.dumps(self._localize_llm_payload(payload), ensure_ascii=False, indent=indent)

    def _localize_llm_payload(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                LLM_PAYLOAD_KEY_TRANSLATIONS.get(str(key), str(key)): self._localize_llm_payload(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._localize_llm_payload(item) for item in value]
        if isinstance(value, tuple):
            return [self._localize_llm_payload(item) for item in value]
        return value

    def generate_master_reply(
        self,
        *,
        user_message: str,
        intent: str,
        state: WorkflowState,
        risk: HealthRiskData,
        nutrition: NutritionAnalysisData,
        recipes: list[RecipeMealItem],
        recommendations: list[str],
        fallback_reply: str,
    ) -> str:
        if not self.enabled or self.client is None:
            return fallback_reply

        try:
            messages = self._build_messages(
                user_message=user_message,
                intent=intent,
                state=state,
                risk=risk,
                nutrition=nutrition,
                recipes=recipes,
                recommendations=recommendations,
                fallback_reply=fallback_reply,
            )
            content = self._complete_chat_with_optional_thinking(
                model=settings.llm_model,
                temperature=settings.llm_temperature,
                max_tokens=settings.llm_max_tokens,
                messages=messages,
            )
            return (content or "").strip() or fallback_reply
        except Exception:
            return fallback_reply

    def stream_master_reply(
        self,
        *,
        user_message: str,
        intent: str,
        state: WorkflowState,
        risk: HealthRiskData,
        nutrition: NutritionAnalysisData,
        recipes: list[RecipeMealItem],
        recommendations: list[str],
        fallback_reply: str,
    ):
        if not self.enabled or self.client is None:
            yield from self._fallback_stream(fallback_reply)
            return

        try:
            messages = self._build_messages(
                user_message=user_message,
                intent=intent,
                state=state,
                risk=risk,
                nutrition=nutrition,
                recipes=recipes,
                recommendations=recommendations,
                fallback_reply=fallback_reply,
            )
            stream = self._stream_chat_with_thinking(
                model=settings.llm_model,
                temperature=settings.llm_temperature,
                max_tokens=settings.llm_max_tokens,
                messages=messages,
            )
            emitted = False
            for event in stream:
                if event["type"] == "answer":
                    emitted = True
                yield event
            if not emitted:
                yield from self._fallback_stream(fallback_reply)
        except Exception:
            yield from self._fallback_stream(fallback_reply)

    def generate_suggested_questions(
        self,
        *,
        workflow_state: WorkflowState,
        assistant_reply: str,
        current_user_message: str = "",
        recent_user_messages: list[dict[str, str]] | None = None,
    ) -> list[str] | None:
        if not self.enabled or self.client is None:
            return None

        context_payload = {
            "current_user_message": current_user_message,
            "recent_user_messages": (recent_user_messages or [])[-LLM_HISTORY_LIMIT:],
            "assistant_reply": assistant_reply,
            "goal": workflow_state.goal,
            "disease": workflow_state.disease,
            "diet_preference": workflow_state.diet_preference,
            "allergy": workflow_state.allergy,
            "latest_route": workflow_state.last_route.intent if workflow_state.last_route else "",
        }
        system_prompt = (
            '只返回 JSON，格式为：{"问题列表":["..."]}。'
            "请生成 3 到 4 条用户下一步可能点击的中文引导问题，并且尽量让用户点击后可以直接生成食谱或菜单。"
            "必须优先参考“当前用户输入”和“近期用户消息”，让问题与当前用户提问和近期连续需求高度相关。"
            "“助手回复”只作为理解本轮回答内容的辅助信息，不能生成泛泛的功能入口问题。"
            "每个问题都要具体、易懂、可执行，优先使用“帮我安排...食谱”“帮我生成...菜单”“按这个目标规划...”这类表达。"
            "不要生成只会得到大段文字建议的问题，例如“有什么建议”“需要注意什么”“怎么执行更好”。"
            "如果用户刚要菜谱，围绕下一餐、明天、未来一周、食材替换后的新菜单继续生成食谱。"
            "如果用户刚做餐前餐后分析，优先生成“下一餐怎么安排”“明天一日三餐怎么安排”“本周食谱怎么调整”这类食谱规划问题。"
            "避免重复当前问题，避免与最近历史无关的问题。"
        )
        try:
            content = self._complete_chat_with_optional_thinking(
                model=settings.llm_model,
                temperature=0.4,
                max_tokens=600,
                messages=[
                    cast(ChatCompletionSystemMessageParam, {"role": "system", "content": system_prompt}),
                    cast(ChatCompletionUserMessageParam, {"role": "user", "content": self._dump_llm_payload(context_payload)}),
                ],
            )
            payload = self._extract_json_payload(content or "")
            questions = payload.get("问题列表") or payload.get("questions")
            if not isinstance(questions, list):
                return None
            normalized = [self._stringify_text(item) for item in questions]
            return [item for item in normalized if item][:4] or None
        except Exception:
            return None

    def route_agent(
        self,
        *,
        user_message: str,
        has_medical_report: bool,
        guard_agent: dict[str, Any],
        agent_catalog: list[dict[str, Any]],
    ) -> dict[str, str] | None:
        if not self.enabled or self.client is None:
            return None

        valid_agent_map = {
            str(item.get("intent")): str(item.get("agent_name"))
            for item in agent_catalog
            if item.get("intent") and item.get("agent_name")
        }
        if not valid_agent_map:
            return None

        system_prompt = (
            "你是健康营养助手的路由层。"
            "当用户的问题是在问吃什么、怎么吃、怎么安排、推荐吃什么、规划明天/本周/某一餐，必须优先选择 recipe_generation。"
            "只有用户明确要求饮食原则、注意事项、执行建议且不需要具体菜谱时，才选择 recommendation。"
            "请根据用户输入只选择 1 个最主要的意图，并且只返回 JSON："
            '{"意图":"...","目标智能体":"...","原因":"..."}'
        )
        user_prompt = self._dump_llm_payload(
            {
                "user_message": user_message,
                "guard_agent": guard_agent,
                "candidate_agents": agent_catalog,
            }
        )
        try:
            with self._suppress_stream_callbacks():
                content = self._complete_chat_with_optional_thinking(
                    model=settings.llm_model,
                    temperature=0.1,
                    max_tokens=300,
                    messages=[
                        cast(ChatCompletionSystemMessageParam, {"role": "system", "content": system_prompt}),
                        cast(ChatCompletionUserMessageParam, {"role": "user", "content": user_prompt}),
                    ],
                )
            print("路由决定",user_prompt)
            print("content",content)
            payload = self._extract_json_payload((content or "").strip())
            print("payload",payload)
            intent = self._normalize_routing_intent(payload.get("意图") or payload.get("intent"))
            print("intent",intent)
            if intent is None or intent not in valid_agent_map:
                print("没有")
                return None
            target_agent = self._stringify_text(payload.get("目标智能体") or payload.get("target_agent")) or valid_agent_map[intent]
            reason = self._stringify_text(payload.get("原因") or payload.get("reason")) or "大模型路由选择了最接近的智能体。"
            return {"intent": intent, "target_agent": target_agent, "reason": reason}
        except Exception:
            return None

    def parse_medical_report_pdf(self, *, file_bytes: bytes, file_name: str, stream_answer: bool = False) -> str:
        pdf_content = self._extract_pdf_text(file_bytes)
        if not pdf_content:
            return ""
        if not self.enabled or self.client is None:
            return pdf_content

        system_prompt = (
            "你是体检报告解析助手。请把提取到的体检报告文本整理成 Markdown 格式的中文报告。（思考过程尽量使用中文，并且推理功能是面向大众普通用户，尽量不要使用英文推理）"
            "必须保留原报告中的测量数据、指标、单位、参考范围和异常发现；不要捏造数据。"
            "输出只允许是 Markdown 正文，不要返回 JSON，不要写代码块。"
        )
        user_prompt = f"文件名：{file_name}\n体检报告全文：\n{pdf_content}\n\n请直接输出 Markdown 格式的体检报告摘要。"
        try:
            print("调用大模型解析报告")
            content = self._complete_chat_with_optional_thinking(
                model=settings.llm_model,
                temperature=0.1,
                max_tokens=2000,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                stream_answer=stream_answer,
            )
            print("体检报告结果",content)
            return (content or "").strip() or pdf_content
        except Exception:
            return pdf_content

    def generate_user_profile_markdown(
        self,
        *,
        medical_report_markdown: str,
        user_message: str,
        stream_answer: bool = False,
    ) -> str | None:
        if not self.enabled or self.client is None:
            return None
        payload = {
            "用户输入问题": user_message,
        }
        system_prompt = (
            "你是用户画像分析助手。请基于用户当前输入、对话上下文和已知饮食偏好，生成一份可直接展示给用户的中文 Markdown 用户画像。（思考过程尽量使用中文，并且推理功能是面向大众普通用户，尽量不要使用英文推理）"
            "只返回 Markdown 正文，不要返回 JSON，不要写代码块。"
            "不要捏造年龄、疾病、医学指标或诊断结论。"
            "重点说明用户当前饮食关注点、口味偏好、食堂点餐倾向和下一步可执行建议。"
        )
        try:
            content = self._complete_chat_with_optional_thinking(
                model=settings.llm_model,
                temperature=0.2,
                max_tokens=1200,
                messages=[
                    cast(ChatCompletionSystemMessageParam, {"role": "system", "content": system_prompt}),
                    cast(ChatCompletionUserMessageParam, {"role": "user", "content": self._dump_llm_payload(payload)}),
                ],
                stream_answer=stream_answer,
            )
            print("用户画像",content)
            return (content or "").strip() or None
        except Exception:
            return None

    def answer_diet_history_question(
        self,
        *,
        user_message: str,
        history_records: list[dict[str, str]],
        stream_answer: bool = False,
    ) -> str | None:
        if not self.enabled or self.client is None:
            return None

        payload = {
            "用户输入": user_message,
            "历史用餐记录": history_records,
        }
        system_prompt = (
            "你是饮食历史分析助手。（思考过程尽量使用中文，并且推理功能是面向大众普通用户，尽量不要使用英文推理）"
            "请只基于用户问题和提供的历史用餐记录附件回答。"
            "附件里的历史用餐记录是数据库真实记录，不要编造附件里没有的内容。"
            "优先给数据，按照日期归类，每一天内，第一次用餐有什么，第二次用餐有什么，以此类推"
            "回答饮食趋势、重复问题、偏油偏咸偏甜、进餐时间特点、食堂点餐调整方向。"
            "如果记录不足以支持结论，要明确说明。"
            "请用简洁、实用、面向普通大众的中文回答。"
        )
        try:
            content = self._complete_chat_with_optional_thinking(
                model=settings.llm_model,
                temperature=0.2,
                max_tokens=1200,
                messages=[
                    cast(ChatCompletionSystemMessageParam, {"role": "system", "content": system_prompt}),
                    cast(ChatCompletionUserMessageParam, {"role": "user", "content": self._dump_llm_payload(payload)}),
                ],
                stream_answer=stream_answer,
            )
            return (content or "").strip() or None
        except Exception:
            return None

    def generate_health_risk_markdown(
        self,
        *,
        medical_report_markdown: str,
        user_message: str,
        stream_answer: bool = False,
    ) -> str | None:
        if not self.enabled or self.client is None:
            return None
        payload = {
            "用户输入": user_message,
        }
        system_prompt = (
            "你是健康饮食忌口分析助手。（思考过程尽量使用中文，并且推理功能是面向大众普通用户，尽量不要使用英文推理）"
            "请只基于用户当前输入、明确说明的忌口、过敏、疾病名称、饮食目标和食堂点餐场景，回答用户需要避免、少吃或注意哪些食物和菜品。"
            "只返回 Markdown 正文，不要返回 JSON，不要写代码块。"
            "不要输出风险等级，不要做风险分级，不要给出确诊结论。"
            "如果用户没有提供足够健康限制信息，要明确说明只能给通用饮食建议。"
            "回答要面向食堂和日常点餐场景，给出具体可执行的避开项、少吃项和替代选择。"
        )
        try:
            content = self._complete_chat_with_optional_thinking(
                model=settings.llm_model,
                temperature=0.2,
                max_tokens=1400,
                messages=[
                    cast(ChatCompletionSystemMessageParam, {"role": "system", "content": system_prompt}),
                    cast(ChatCompletionUserMessageParam, {"role": "user", "content": self._dump_llm_payload(payload)}),
                ],
                stream_answer=stream_answer,
            )
            print("风险")
            return (content or "").strip() or None
        except Exception:
            return None

    def generate_recommendations(
        self,
        *,
        workflow_state: WorkflowState,
        user_profile: UserProfileData,
        medical_report: str | None,
        risk: HealthRiskData | None,
        season: str,
        month_label: str,
        time_of_day: str,
        current_datetime: str,
    ) -> list[str] | None:
        if not self.enabled or self.client is None:
            return None
        payload = {
            "目标": workflow_state.goal or "未明确",
            "地区": "未明确",
            "饮食偏好": workflow_state.diet_preference,
            "过敏信息": workflow_state.allergy,
            "健康限制": workflow_state.disease,
            "季节": season,
            "月份": month_label,
            "当前时段": time_of_day,
            "当前日期时间": current_datetime,
        }
        system_prompt = (
            '只返回 JSON，格式为：{"推荐建议":["..."]}。'
            "请生成简洁、实用的中文建议。"
            "本产品主要服务食堂场景和普通大众，所以优先给出怎么选菜、怎么搭主食、怎么选汤、怎么控制分量这类建议。"
        )
        try:
            content = self._complete_chat_with_optional_thinking(
                model=settings.llm_model,
                temperature=0.3,
                max_tokens=1200,
                messages=[
                    cast(ChatCompletionSystemMessageParam, {"role": "system", "content": system_prompt}),
                    cast(ChatCompletionUserMessageParam, {"role": "user", "content": self._dump_llm_payload(payload)}),
                ],
            )
            data = self._extract_json_payload((content or "").strip())
            items = data.get("推荐建议") or data.get("recommendations")
            return self._normalize_string_list(items) or None
        except Exception:
            return None

    def generate_recipe_plan(
        self,
        *,
        workflow_state: WorkflowState,
        user_profile: UserProfileData,
        medical_report: str | None,
        risk: HealthRiskData | None,
        nutrition: NutritionAnalysisData,
        region: str,
        season: str,
        month_label: str,
        time_of_day: str,
        current_datetime: str,
        user_message: str,
        plan_scope: str,
        recent_history: list[dict[str, str]],
        stream_answer: bool = False,
    ) -> str | None:
        if not self.enabled or self.client is None:
            return None

        recipe_filter_conditions = self.generate_recipe_filter_conditions(
            medical_report_markdown="",
            user_message=user_message,
            current_season=season,
            default_region=region,
            recent_history=recent_history[-LLM_HISTORY_LIMIT:],
        )
        print("数据库过滤词语",recipe_filter_conditions)
        recipe_database_candidates = self._load_recipe_database_candidates(
            conditions=recipe_filter_conditions,
            plan_scope=plan_scope,
        )
        # print("recipe_database_candidates",recipe_database_candidates)
        recipe_region_priority = recipe_database_candidates.get("_region_priority", {})
        candidate_meal_plan = self._build_candidate_meal_plan(
            candidates=recipe_database_candidates,
            plan_scope=plan_scope,
        )

        payload = {
            # "用户输入": user_message,
            # "计划范围": plan_scope,
            # "目标": workflow_state.goal or "未明确",
            # "地区": region,
            # "饮食偏好": workflow_state.diet_preference,
            # "过敏信息": workflow_state.allergy,
            # "健康限制": workflow_state.disease,
            # "营养目标": nutrition.model_dump(mode="json"),
            # "季节": season,
            # "月份": month_label,
            # "当前时段": time_of_day,
            # "当前日期时间": current_datetime,
            "近期对话": recent_history[-LLM_HISTORY_LIMIT:],
            "食谱数据库筛选条件": recipe_filter_conditions,
            "食谱地区优先级": recipe_region_priority,
            "食谱数据库候选": recipe_database_candidates,
            "候选餐次计划": candidate_meal_plan,
        }
        meal_count = 28 if plan_scope == "week" else 4
        scope_text = "一周饮食计划" if plan_scope == "week" else "一天饮食计划"
        scope_text = "饮食计划"
        print("系统提示词")
        system_prompt = """
        你是面向单位食堂和团餐运营场景的 B 端饮食规划智能体，负责为企业、学校、园区、医院职工食堂等单位食堂生成可执行、可审核、可直接展示的健康供餐计划（思考过程尽量使用中文，并且推理功能是面向食堂管理员、后勤人员和普通用餐人群，尽量不要使用英文推理）。

        【输出格式】
        1. 仅返回 Markdown 内容。
        2. 禁止返回 JSON、代码块、格式说明。
        3. Markdown 内容必须适合食堂管理员、后勤管理人员、营养管理人员和普通用餐人群直接阅读。
        4. 答案开头必须先输出一段“总体规划思路”，用 1 到 2 个自然段说明本次单位食堂菜单为什么这样安排，包括单位输入要求、单位和单位人群特点、食堂供餐可执行性、菜品数据库候选、季节/日期、忌口因素和团餐稳定供应要求。
        5. 总体规划思路之后，主体内容必须尽量使用 Markdown 表格输出，不要大段列表堆砌。
        6. 每一天必须按照以下顺序输出：
           早餐、午餐、晚餐、加餐。


        【菜品风格】
        1. 菜品应符合中国单位食堂、团餐和职工餐日常供餐习惯。
        2. 必须优先使用附加信息“候选餐次计划”中已经从数据库筛选出来的菜品组合；不要凭空新增数据库外的菜品，除非候选数据为空或明显不足。
        3. 如果附加信息“食谱地区优先级”中存在“用户输入具体地区类”，必须优先使用这些具体地区候选菜品；只有具体地区候选不足以完成餐次搭配时，才使用“通用补充类”菜品补齐。
        4. 菜品名称要朴实自然，避免营销化、网红化、健身餐化命名。
        5. 禁止出现以下模板化名称：
           早餐杯、能量碗、定食、轻食盘、沙拉碗。
        6. 注意荤素搭配、主副食搭配、蛋白质与蔬菜搭配，并兼顾食堂批量供餐的稳定性。
        7. 菜谱必须贴近单位食堂真实可供应菜品，避免个人定制化、家庭厨房化或高成本小众菜品。

        【健康约束】
        1. 必须严格尊重用户明确提供的单位人群健康背景、过敏信息、禁忌食物、常见慢病饮食限制、饮食目标和生活方式。
        2. 不得推荐与单位人群健康限制冲突的食物。
        3. 必须结合当前季节、当前时间背景、单位食堂供餐场景和当地饮食习惯，但输出中禁止出现具体地名。
        4. 所有饮食建议应偏向单位食堂可规模化执行、普通职工/学生可接受的健康搭配，不追求复杂、昂贵或小众食材。

        【禁止输出内容】
        1. 禁止输出烹饪方式。
        2. 禁止输出烹饪步骤。
        3. 禁止输出食材处理方式，例如：切条、切段、去皮、切块、蒸熟等。
        4. 禁止输出烹饪细节，例如：少盐、不勾芡、清蒸、少油、焯水、腌制等。
        5. 禁止出现“适合食堂及家庭日常制作”等类似说明。
        6. 禁止出现“家常”相关字样。
        7. 禁止出现具体地名。
        8. 禁止输出食材配方、制作比例、调味料比例或做法说明。

        【每餐必须包含的内容】
        每一餐必须优先使用表格输出，必须包含以下四类信息：
        1. 本餐菜品
           说明：
           - 午餐和晚餐必须3到5个菜
           - 不能是食材，一定要是做好的成品
           - 建议在同一张表格中用“餐次、菜品组合、食物元素归类、营养估算、本餐说明”这些列展示

        2. 食物元素归类
           按以下类别列出本餐食材及估算重量（最多显示3个）。元素归类是对菜品食材的归类，不是对菜品名称的归类：
           - 主食/碳水
           - 优质蛋白
           - 蔬菜
           - 水果
           - 奶豆类
           - 油脂坚果

           说明：
           - 必须优先使用“候选餐次计划”中每个菜品的“食材”和“食材分类”字段。
           - “食材分类”已经由后端根据数据库食材字段预先归类，大模型不要重新把菜品名复制到“食物元素归类”里。
           - 禁止把“红烧鱼”“青椒肉丝”“紫菜蛋花汤”这类菜品名写进食物元素归类；只能写“鱼、猪肉、青椒、紫菜、鸡蛋、米饭”等食材。
           - 如果 ingredient_categories 已经给出分类，请直接沿用这些分类，并只补充合理克数估算。
           - 如果某一类本餐没有，就不需要输出该类。
           - 这里只写食材和估算重量，不写做法、处理方式或烹饪细节。
           - 在表格中用“主食/碳水：米饭 150g；优质蛋白：鱼 80g；蔬菜：青菜 120g”这种紧凑格式展示。

        3. 本餐营养估算  
           显式列出以下营养数值（最多显示4个）：
           - 热量：xx kcal
           - 蛋白质：xx g
           - 碳水：xx g
           - 脂肪：xx g
           - 膳食纤维：xx g
           - 钠：xx mg
           - 糖：xx g
           
           说明：
           - 以上营养数值估算最多显示4个
           - 在表格中用“热量 650kcal；蛋白质 32g；碳水 78g；脂肪 18g”这种紧凑格式展示。

        4. 本餐说明  
           用一句话说明本餐营养搭配特点。
           不得出现烹饪方式、烹饪步骤、食材处理方式、具体地名或“家常”等字样。

        【每日汇总】
        每天结束后必须增加“每日总量汇总”，并用 Markdown 表格汇总当天以下营养数据：
        | 总热量 | 蛋白质 | 碳水 | 脂肪 | 膳食纤维 | 钠 | 糖 |
        |---|---|---|---|---|---|---|
        | xx kcal | xx g | xx g | xx g | xx g | xx mg | xx g |

        【周食谱要求】
        如果用户要求生成一周食谱：
        1. 默认每天包含早餐、午餐、晚餐、加餐，否则判断是否完整生成早餐、午餐、晚餐、加餐四餐，首先必须严格要求用户的问题输入要求，比如用户要求规划午餐和晚餐的食谱，则不准额外生成早餐和加餐。其次查看最近历史记录，历史记录生成了几餐就生成几餐。
        2. 每天都必须包含“每日总量汇总”。
        3. 最后必须增加“本周总结”，并尽量使用表格输出。
        4. 本周总结必须包含平均每日热量、平均每日蛋白质、平均每日碳水、平均每日脂肪、主要营养风险。
        5. 本周总结不得包含烹饪建议、制作建议或地名。
        如果用户要求生成一天中的具体某一餐，则只生成某一餐。

        【日期规则】
        1. 必须严格根据用户问题、当前时间和今天星期几计算日期。
        2. 如果用户说“下周”或“下一周”，第一天必须是当前日期所在周的下一周星期一，不能使用今天日期。
        3. 如果用户说“明天”，必须使用当前日期加一天。
        4. 如果用户说“一周”“未来一周”但没有说下周，默认从明天开始连续安排 7 天。
        5. 每天标题必须写成“## 星期x（YYYY-MM-DD）”。
        6. 不确定时，以用户问题中的明确日期为准；没有明确日期时，以当前时间为准。

        【数值要求】
        1. 所有营养数值允许合理估算，但必须显式写出。
        2. 克数、热量和营养数值要尽量保持逻辑一致。
        3. 每日总量必须与当天各餐估算值基本匹配。
        4. 一周内菜品尽量避免高度重复，尤其是午餐和晚餐主菜。
        5. 每天的菜尽量不一样，相邻两天内的早餐、午餐主菜、晚餐主菜、汤品和加餐尽量不重复。
        6. 如果“候选餐次计划”已经给出某天的早餐、午餐、晚餐和加餐，请以该组合为基础进行语言整理和营养估算，不要随意替换。
        7. 食物元素归类必须基于数据库菜品的“食材/食材分类”计算，不允许直接复用菜品名称。

        【推荐输出结构示例】
        ## 总体规划思路
        本次饮食计划优先基于用户当前问题、明确提出的忌口或偏好、当前季节日期和食堂菜品数据库候选进行安排。整体思路是控制明显不适合的菜品，保证主食、优质蛋白和蔬菜的基本比例，同时让每天菜品尽量不重复，便于食堂按周执行。

        ## 周一（2026-xx-xx）

        | 餐次 | 菜品组合 | 食物元素归类 | 本餐营养估算 | 本餐说明 |
        |---|---|---|---|---|
        | 早餐 | 鸡蛋、杂粮粥、青菜、牛奶 | 主食/碳水：杂粮粥 250g；优质蛋白：鸡蛋 50g；蔬菜：青菜 100g；奶豆类：牛奶 250ml | 热量 xxx kcal；蛋白质 xx g；碳水 xx g；脂肪 xx g | 主食、蛋白质和奶类搭配较均衡，适合作为上午能量来源。 |
        | 午餐 | 主食、汤品、荤菜、素菜 | 主食/碳水：xx；优质蛋白：xx；蔬菜：xx | 热量 xxx kcal；蛋白质 xx g；碳水 xx g；脂肪 xx g | 午餐保证主副食和蔬菜比例，适合食堂中午供餐。 |
        | 晚餐 | 主食、汤品、荤菜、素菜 | 主食/碳水：xx；优质蛋白：xx；蔬菜：xx | 热量 xxx kcal；蛋白质 xx g；碳水 xx g；脂肪 xx g | 晚餐整体不过量，保留足够蛋白质和蔬菜。 |
        | 加餐 | 点心或主食类加餐 | 主食/碳水：xx | 热量 xxx kcal；碳水 xx g；脂肪 xx g | 加餐用于补充能量，不宜过量。 |

        ### 每日总量汇总
        | 总热量 | 蛋白质 | 碳水 | 脂肪 | 膳食纤维 | 钠 | 糖 |
        |---|---|---|---|---|---|---|
        | xxxx kcal | xx g | xx g | xx g | xx g | xx mg | xx g |

        ## 本周总结
        | 平均每日热量 | 平均每日蛋白质 | 平均每日碳水 | 平均每日脂肪 | 主要营养风险 |
        |---|---|---|---|---|
        | xxxx kcal | xx g | xx g | xx g | 简短说明 |
        """
        today = datetime.now()
        weekday = today.weekday()
        week_map = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        user_prompt = (
            # f"请生成{scope_text}。\n"
            f"用户的问题输入要求：{user_message}\n"
            "是否完整生成早餐、午餐、晚餐、加餐，首先必须严格要求用户的问题输入要求，比如用户要求规划午餐和晚餐的食谱，则不准额外生成早餐和加餐。其次查看最近历史记录，历史记录生成了几餐就生成几餐\n"
            # f"用户的地区在附加信息中\n"
            # f"当前季节：{season}\n"
            f"当前时间：{current_datetime}（{time_of_day}）\n"
            f"今天{week_map[weekday]}\n"
            # f"食谱范围：{scope_text}\n"
            # f"数据库筛选条件：{self._dump_llm_payload(recipe_filter_conditions)}\n"
            "请结合附加信息中的“近期对话”字段理解用户最近的连续需求、忌口、口味、补充条件和上下文，不要只看当前这一句。\n"
            "如果附加信息“食谱地区优先级”里有用户输入具体地区类，请优先从该类菜品生成食谱；只有具体地区类菜品不足时，再使用通用补充类补齐，不要反过来优先使用通用菜品。\n"
            "请优先使用附加信息中的“候选餐次计划”作为菜品来源；如果用户没有在输入中规定每餐怎么去搭配，则默认午餐和晚餐按“主食1个+汤1个+荤菜1个+素菜1个”整理，水产类按荤菜处理；早餐从早餐类选择1到2个；加餐从主食类或早餐类选择1个。\n"
            "食物元素归类必须使用“候选餐次计划”中每道菜的“食材”和“食材分类”字段，只允许基于这些食材重新估算克数和营养，不允许把菜品名复制到食物元素归类里。\n"
            "最终答案必须先输出“## 总体规划思路”，写一段思考性总概述；之后每天的早餐、午餐、晚餐、加餐尽量用Markdown表格展示，表格至少包含餐次、菜品组合、食物元素归类、本餐营养估算、本餐说明。\n"
            "每天的菜尽量不一样，相邻两天内的菜谱尽量不一样。\n"
            # "请直接输出 Markdown，不要输出 JSON。\n\n"
            f"结合以下附加信息{self._dump_llm_payload(payload, indent=2)}"
        )
        print("payload",payload)
        # print(system_prompt)
        # print(user_prompt)



        try:
            # print("用户提示词",user_prompt)
            print("进入生成")
            content = self._complete_chat_with_optional_thinking(
                model=settings.llm_model,
                temperature=0.4,
                max_tokens=5000,
                messages=[
                    cast(ChatCompletionSystemMessageParam, {"role": "system", "content": system_prompt}),
                    cast(ChatCompletionUserMessageParam, {"role": "user", "content": user_prompt}),
                ],
                stream_answer=stream_answer,
            )
            return (content or "").strip() or None
        except Exception:
            return None

    def generate_recipe_filter_conditions(
        self,
        *,
        medical_report_markdown: str,
        user_message: str,
        current_season: str,
        default_region: str,
        recent_history: list[dict[str, str]],
    ) -> dict[str, Any]:
        normalized_current_season = current_season.replace("季", "") or "四季"
        default_conditions = {
            "season": self._normalize_filter_values(["四季", normalized_current_season]),
            "region": self._normalize_filter_values(["通用", default_region if default_region and default_region != "未明确" else ""]),
            "people_type": "普通职工",
            "avoid_people": [],
        }
        if not self.enabled or self.client is None:
            return default_conditions

        system_prompt = (
            "实时思考过程一定要使用中文"
            "你是单位食堂 B 端饮食规划系统中的食谱数据库筛选条件生成助手。请根据用户问题、最近对话、当前季节和默认地区，"
            "为企业、学校、园区、医院职工食堂等团餐场景生成后续查询菜品数据库所需的筛选条件。"
            "只返回 JSON，不要返回 Markdown，不要写代码块。JSON 格式固定为："
            '{"season":["四季","夏"],"region":["通用","江苏"],"people_type":"普通职工","avoid_people":["控糖","高血压"]}。'
            "season 必须是数组，且必须包含“四季”；如果能判断当前季节，再追加春、夏、秋、冬中的一个。"
            "region 必须是数组，且必须包含“通用”；如果能判断地区，再追加该地区，例如浙江、广东、河南等。"
            "people_type 默认返回普通职工；如果单位场景明确是学校、养老机构、医院或其他集体供餐人群，可以返回学生、老人、医护职工、夜班职工等更贴近单位食堂的人群类型。"
            "avoid_people 用数组返回需要规避的健康标签，例如控糖、高血压、高血脂、高尿酸、减脂、低盐、低脂、胃部不适等。"
            "不要输出解释。"
        )
        user_prompt = json.dumps(
            {
                "user_message": user_message,
                "current_season": current_season,
                "default_region": default_region,
                "recent_history": recent_history,
            },
            ensure_ascii=False,
        )
        try:
            content = self._complete_chat_with_optional_thinking(
                model=settings.llm_model,
                temperature=0.1,
                max_tokens=500,
                messages=[
                    cast(ChatCompletionSystemMessageParam, {"role": "system", "content": system_prompt}),
                    cast(ChatCompletionUserMessageParam, {"role": "user", "content": user_prompt}),
                ],
            )
            payload = self._extract_json_payload(content or "")
            season = self._normalize_filter_values(["四季", *self._normalize_string_list(payload.get("season"))])
            region = self._normalize_filter_values(["通用", *self._normalize_string_list(payload.get("region"))])
            people_type = self._stringify_text(payload.get("people_type")) or "普通职工"
            avoid_people = self._normalize_string_list(payload.get("avoid_people"))
            season = [item for item in season if item in {"春", "夏", "秋", "冬", "四季"}]
            if not season:
                season = default_conditions["season"]
            if not region:
                region = default_conditions["region"]
            return {
                "season": season,
                "region": region,
                "people_type": people_type,
                "avoid_people": avoid_people,
            }
        except Exception:
            return default_conditions

    def _load_recipe_database_candidates(
        self,
        *,
        conditions: dict[str, Any],
        plan_scope: str,
    ) -> dict[str, Any]:
        try:
            from sqlalchemy import inspect, text
            from app.db.session import engine

            inspector = inspect(engine)
            table_names = inspector.get_table_names()
            print("食谱数据库表", table_names)
            limit = 80 if plan_scope == "week" else 24
            specific_regions = self._specific_recipe_regions(conditions.get("region"))
            candidates: dict[str, Any] = {}
            region_specific_candidates: dict[str, list[dict[str, Any]]] = {}
            region_common_candidates: dict[str, list[dict[str, Any]]] = {}
            with engine.connect() as connection:
                for category, table_candidates in RECIPE_CATEGORY_TABLE_CANDIDATES.items():
                    table_name = self._find_recipe_table_name(table_names, table_candidates, category)
                    if not table_name:
                        print("食谱数据库未找到分类表", category, table_candidates)
                        candidates[category] = []
                        region_specific_candidates[category] = []
                        region_common_candidates[category] = []
                        continue
                    columns = [item["name"] for item in inspector.get_columns(table_name)]
                    rows = self._query_recipe_rows(
                        connection=connection,
                        table_name=table_name,
                        columns=columns,
                        conditions=conditions,
                        limit=limit,
                        text_fn=text,
                    )
                    print("食谱数据库查询结果", category, table_name, "rows=", len(rows))
                    normalized_rows = [
                        normalized
                        for row in rows
                        if (normalized := self._normalize_recipe_database_row(row, category=category))
                    ]
                    if specific_regions:
                        specific_items, common_items = self._split_recipe_rows_by_region(
                            normalized_rows,
                            specific_regions=specific_regions,
                        )
                        candidates[category] = [*specific_items, *common_items]
                        region_specific_candidates[category] = specific_items
                        region_common_candidates[category] = common_items
                    else:
                        candidates[category] = normalized_rows
                        region_specific_candidates[category] = []
                        region_common_candidates[category] = normalized_rows
            if specific_regions:
                candidates["_region_priority"] = {
                    "specific_regions": specific_regions,
                    "用户输入具体地区类": region_specific_candidates,
                    "通用补充类": region_common_candidates,
                    "usage_rule": "生成菜谱时优先使用用户输入具体地区类；如果具体地区候选不足，再使用通用补充类补齐。",
                }
            return candidates
        except Exception as exc:
            print(exc)
            print("食谱数据库候选查询失败", repr(exc))
            return {category: [] for category in RECIPE_CATEGORY_TABLE_CANDIDATES}

    def _specific_recipe_regions(self, region_value: Any) -> list[str]:
        ignored = {"通用", "未明确", "全国", "不限", "全部", "默认"}
        return [item for item in self._normalize_filter_values(region_value) if item not in ignored]

    def _split_recipe_rows_by_region(
        self,
        rows: list[dict[str, Any]],
        *,
        specific_regions: list[str],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        specific_items: list[dict[str, Any]] = []
        common_items: list[dict[str, Any]] = []
        for row in rows:
            region_text = self._stringify_text(row.get("region"))
            if region_text and any(region in region_text for region in specific_regions):
                specific_items.append(row)
            else:
                common_items.append(row)
        return specific_items, common_items

    def _find_recipe_table_name(
        self,
        table_names: list[str],
        candidates: list[str],
        category: str,
    ) -> str | None:
        lowered = {name.lower(): name for name in table_names}
        for candidate in candidates:
            if candidate.lower() in lowered:
                return lowered[candidate.lower()]

        keyword_map = {
            "soup": ["soup", "汤"],
            "staple": ["staple", "main_food", "主食"],
            "vegetable": ["vegetable", "素菜", "蔬菜"],
            "meat": ["meat", "荤菜"],
            "aquatic": ["aquatic", "水产", "鱼", "虾"],
            "breakfast": ["breakfast", "早餐"],
        }
        for table_name in table_names:
            normalized = table_name.lower()
            if any(keyword in normalized or keyword in table_name for keyword in keyword_map.get(category, [])):
                return table_name
        return None

    def _query_recipe_rows(
        self,
        *,
        connection: Any,
        table_name: str,
        columns: list[str],
        conditions: dict[str, Any],
        limit: int,
        text_fn: Callable[[str], Any],
    ) -> list[dict[str, Any]]:
        where_parts: list[str] = []
        params: dict[str, Any] = {"limit": limit}

        season_col = self._pick_column(columns, ["season", "季节", "适用季节"])
        season_values = self._normalize_filter_values(conditions.get("season"))
        if season_col and season_values:
            season_conditions = [f"`{season_col}` LIKE :season_{index}" for index, _ in enumerate(season_values)]
            where_parts.append(f"(`{season_col}` IS NULL OR `{season_col}` = '' OR {' OR '.join(season_conditions)})")
            for index, item in enumerate(season_values):
                params[f"season_{index}"] = f"%{item}%"

        region_col = self._pick_column(columns, ["region", "area", "地区", "地域", "菜系"])
        region_values = self._normalize_filter_values(conditions.get("region"))
        if region_col and region_values:
            region_conditions = [f"`{region_col}` LIKE :region_{index}" for index, _ in enumerate(region_values)]
            where_parts.append(f"(`{region_col}` IS NULL OR `{region_col}` = '' OR {' OR '.join(region_conditions)})")
            for index, item in enumerate(region_values):
                params[f"region_{index}"] = f"%{item}%"

        people_col = self._pick_column(columns, ["people_type", "suitable_people", "适用人群", "人群", "适合人群"])
        if people_col and conditions.get("people_type"):
            where_parts.append(
                f"(`{people_col}` IS NULL OR `{people_col}` = '' OR `{people_col}` LIKE :people_type OR `{people_col}` LIKE :common_people)"
            )
            params["people_type"] = f"%{conditions['people_type']}%"
            params["common_people"] = "%普通%"

        avoid_col = self._pick_column(columns, ["avoid_people", "forbidden_people", "禁忌人群", "不适合人群", "避免人群"])
        avoid_people = self._normalize_string_list(conditions.get("avoid_people"))
        if avoid_col and avoid_people:
            for index, item in enumerate(avoid_people[:8]):
                key = f"avoid_{index}"
                where_parts.append(f"(`{avoid_col}` IS NULL OR `{avoid_col}` = '' OR `{avoid_col}` NOT LIKE :{key})")
                params[key] = f"%{item}%"

        where_sql = f" WHERE {' AND '.join(where_parts)}" if where_parts else ""
        sql = f"SELECT * FROM `{table_name}`{where_sql} LIMIT :limit"
        result = connection.execute(text_fn(sql), params)
        return [dict(row._mapping) for row in result]

    def _normalize_filter_values(self, value: Any) -> list[str]:
        values = self._normalize_string_list(value)
        normalized: list[str] = []
        seen: set[str] = set()
        for item in values:
            text = item.strip()
            if text in {"春季", "夏季", "秋季", "冬季"}:
                text = text.replace("季", "")
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(text)
        return normalized

    def _pick_column(self, columns: list[str], candidates: list[str]) -> str | None:
        lowered = {column.lower(): column for column in columns}
        for candidate in candidates:
            if candidate.lower() in lowered:
                return lowered[candidate.lower()]
        for column in columns:
            normalized = column.lower()
            if any(candidate.lower() in normalized or candidate in column for candidate in candidates):
                return column
        return None

    def _normalize_recipe_database_row(self, row: dict[str, Any], *, category: str) -> dict[str, Any] | None:
        name = self._row_column_value(row, ["name", "dish_name", "recipe_name", "food_name", "title", "菜品名称", "名称", "菜名"])
        if not name:
            return None
        ingredients = self._normalize_recipe_ingredient_text(
            self._row_column_value(
                row,
                ["ingredients", "ingredient", "materials", "food_materials", "raw_materials", "食材", "主要食材", "原料", "配料"],
            )
        )
        normalized = {
            "name": name,
            "category": category,
            "ingredients": ingredients,
            "ingredient_categories": self._classify_recipe_ingredients(ingredients, dish_category=category),
            "season": self._row_column_value(row, ["season", "季节", "适用季节"]),
            "region": self._row_column_value(row, ["region", "area", "地区", "地域", "菜系"]),
            "people_type": self._row_column_value(row, ["people_type", "suitable_people", "适用人群", "人群", "适合人群"]),
            "avoid_people": self._row_column_value(row, ["avoid_people", "forbidden_people", "禁忌人群", "不适合人群", "避免人群"]),
            "calories": self._row_column_value(row, ["calories", "calories_kcal", "energy", "热量", "能量"]),
            "protein": self._row_column_value(row, ["protein", "protein_g", "蛋白质"]),
            "carbohydrate": self._row_column_value(row, ["carbohydrate", "carbohydrate_g", "carbs", "碳水", "碳水化合物"]),
            "fat": self._row_column_value(row, ["fat", "fat_g", "脂肪"]),
        }
        return {key: value for key, value in normalized.items() if value not in ("", None)}

    def _row_column_value(self, row: dict[str, Any], candidates: list[str]) -> str:
        picked = self._pick_column(list(row.keys()), candidates)
        return self._stringify_text(row.get(picked)) if picked is not None else ""

    def _normalize_recipe_ingredient_text(self, value: Any) -> list[str]:
        text = self._stringify_text(value)
        if not text:
            return []
        normalized = (
            text.replace("，", ",")
            .replace("、", ",")
            .replace("；", ",")
            .replace(";", ",")
            .replace("|", ",")
            .replace("/", ",")
        )
        ingredients: list[str] = []
        seen: set[str] = set()
        for segment in normalized.split(","):
            item = segment.strip()
            if not item or item in seen:
                continue
            seen.add(item)
            ingredients.append(item)
        return ingredients

    def _classify_recipe_ingredients(self, ingredients: list[str], *, dish_category: str) -> dict[str, list[str]]:
        categories = {
            "主食/碳水": [],
            "优质蛋白": [],
            "蔬菜": [],
            "水果": [],
            "奶豆类": [],
            "油脂坚果": [],
        }
        keyword_map = {
            "主食/碳水": [
                "米", "饭", "粥", "面", "粉", "馒头", "包子", "饼", "吐司", "面包", "年糕", "糍粑",
                "土豆", "红薯", "山药", "玉米", "南瓜", "芋", "藕", "燕麦", "小米", "大米", "糯米",
            ],
            "优质蛋白": [
                "鸡", "鸭", "鹅", "猪", "牛", "羊", "肉", "排骨", "里脊", "虾", "鱼", "蟹", "贝",
                "蛤", "蚝", "海参", "鳝", "蛋", "鸡蛋", "鸭蛋", "豆腐", "香干", "豆干",
            ],
            "蔬菜": [
                "菜", "青菜", "白菜", "生菜", "菠菜", "油麦菜", "芹菜", "韭菜", "蒜苔", "豆芽",
                "黄瓜", "冬瓜", "丝瓜", "苦瓜", "茄子", "番茄", "西红柿", "辣椒", "青椒", "胡萝卜",
                "萝卜", "木耳", "香菇", "蘑菇", "金针菇", "笋", "洋葱", "海带", "紫菜",
            ],
            "水果": ["苹果", "香蕉", "梨", "橙", "橘", "柚", "葡萄", "蓝莓", "草莓", "西瓜", "桃", "枣", "桂圆"],
            "奶豆类": ["牛奶", "酸奶", "奶", "豆浆", "豆腐", "豆干", "香干", "腐竹", "黄豆", "绿豆", "红豆"],
            "油脂坚果": ["油", "黄油", "奶油", "花生", "核桃", "杏仁", "坚果", "芝麻", "沙拉酱"],
        }
        for ingredient in ingredients:
            matched = False
            for category, keywords in keyword_map.items():
                if any(keyword in ingredient for keyword in keywords):
                    categories[category].append(ingredient)
                    matched = True
                    break
            if not matched:
                if dish_category in {"meat", "aquatic"}:
                    categories["优质蛋白"].append(ingredient)
                elif dish_category == "staple":
                    categories["主食/碳水"].append(ingredient)
                elif dish_category == "vegetable":
                    categories["蔬菜"].append(ingredient)
        return {category: items for category, items in categories.items() if items}

    def _first_row_value(self, row: dict[str, Any], candidates: list[str]) -> str:
        keys = list(row.keys())
        picked = self._pick_column(keys, candidates)
        if picked is not None:
            return self._stringify_text(row.get(picked))
        for value in row.values():
            text = self._stringify_text(value)
            if text:
                return text
        return ""

    def _build_candidate_meal_plan(
        self,
        *,
        candidates: dict[str, list[dict[str, Any]]],
        plan_scope: str,
    ) -> list[dict[str, Any]]:
        day_count = 7 if plan_scope == "week" else 1
        day_labels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][:day_count]
        breakfast_items = candidates.get("breakfast") or []
        staple_items = candidates.get("staple") or []
        soup_items = candidates.get("soup") or []
        vegetable_items = candidates.get("vegetable") or []
        protein_items = (candidates.get("meat") or []) + (candidates.get("aquatic") or [])

        meal_plan: list[dict[str, Any]] = []
        for day_index, day_label in enumerate(day_labels):
            breakfast_count = 2 if len(breakfast_items) >= day_count * 2 else 1
            breakfast = self._pick_rotating_items(breakfast_items, day_index * breakfast_count, breakfast_count)
            lunch = {
                "主食": self._pick_rotating_items(staple_items, day_index * 2, 1),
                "汤": self._pick_rotating_items(soup_items, day_index * 2, 1),
                "荤菜": self._pick_rotating_items(protein_items, day_index * 2, 1),
                "素菜": self._pick_rotating_items(vegetable_items, day_index * 2, 1),
            }
            dinner = {
                "主食": self._pick_rotating_items(staple_items, day_index * 2 + 1, 1),
                "汤": self._pick_rotating_items(soup_items, day_index * 2 + 1, 1),
                "荤菜": self._pick_rotating_items(protein_items, day_index * 2 + 1, 1),
                "素菜": self._pick_rotating_items(vegetable_items, day_index * 2 + 1, 1),
            }
            snack_source = breakfast_items if day_index % 2 else staple_items
            snack = self._pick_rotating_items(snack_source, day_index + 3, 1)
            meal_plan.append(
                {
                    "day_label": day_label,
                    "早餐": breakfast,
                    "午餐": lunch,
                    "晚餐": dinner,
                    "加餐": snack,
                }
            )
        return meal_plan

    def _pick_rotating_items(self, items: list[dict[str, Any]], start: int, count: int) -> list[dict[str, Any]]:
        if not items or count <= 0:
            return []
        picked: list[dict[str, Any]] = []
        seen: set[str] = set()
        for offset in range(len(items)):
            item = items[(start + offset) % len(items)]
            name = self._stringify_text(item.get("name"))
            if not name or name in seen:
                continue
            picked.append(item)
            seen.add(name)
            if len(picked) >= count:
                break
        return picked

    def analyze_single_meal_image(
        self,
        *,
        image_bytes: bytes,
        image_name: str,
        user_message: str | None = None,
        stream_answer: bool = False,
    ) -> str | None:
        if not self.enabled or self.client is None:
            return None

        try:
            image_url = self._image_bytes_to_data_url(image_bytes, image_name)
            prompt = (
                "你是营养师和餐食图片识别助手。请分析这张单张食物图片，直接返回 markdown 正文，"
                "不要返回 JSON，不要写代码块，不要只给宽泛结论。\n"
                "请严格基于图片可见内容回答；看不清或无法确定时，用“可能是/不确定”说明，不要编造。\n"
                "如果用户还提了问题，请把用户问题作为重点一起回答。\n\n"
                "输出要求：\n"
                "1. 尽量逐项识别图片里的每一种食物、饮品、汤品或调料。\n"
                "2. 对每项食物估算份量，优先使用“碗/拳头/掌心/勺/个/片/份”等生活化单位，并补充大致克数范围。\n"
                "3. 给出这一餐的总热量、碳水、蛋白质、脂肪估算；不确定时必须给范围。\n"
                "4. 分析餐食结构是否均衡：主食、优质蛋白、蔬菜、水果/奶豆、油脂/高盐高糖来源是否足够或偏多。\n"
                "5. 建议必须具体到可操作替换或增减，例如“米饭减少三分之一”“补充1个鸡蛋或一份豆腐”“少喝汤底”。\n"
                "6. 每个判断都要对应图片中看见的食物，不要写“注意均衡饮食”这类空泛建议。\n\n"
                "请优先使用以下结构：\n"
                "## 单张餐食图片分析\n"
                "### 识别到的食物与份量估算\n"
                "| 食物 | 判断依据 | 估算份量 | 估算克数 | 食物类别 | 不确定性 |\n"
                "| --- | --- | --- | --- | --- | --- |\n"
                "### 营养估算\n"
                "| 指标 | 估算值 | 说明 |\n"
                "| --- | --- | --- |\n"
                "| 总热量 | 约xx-xx千卡 | 根据可见食物和份量估算 |\n"
                "| 碳水化合物 | 约xx-xx克 | 主要来自... |\n"
                "| 蛋白质 | 约xx-xx克 | 主要来自... |\n"
                "| 脂肪 | 约xx-xx克 | 主要来自... |\n"
                "### 这一餐的结构判断\n"
                "- 主食：说明是否偏多、适中或偏少，并说明依据。\n"
                "- 蛋白质：说明是否足够，并说明依据。\n"
                "- 蔬菜和膳食纤维：说明是否足够，并说明依据。\n"
                "- 油盐糖风险：如有煎炸、浓汤、酱料、甜饮等，请明确指出。\n"
                "### 具体调整建议\n"
                "- 给出3-5条具体、可执行的调整建议。\n"
                "### 如果要记录到饮食日记\n"
                "- 用一句话总结这餐的记录内容。\n"
            )
            if user_message:
                prompt = f"{prompt}\n用户问题：{user_message}"

            text = self._complete_chat_with_optional_thinking(
                model=settings.llm_model,
                temperature=0.2,
                max_tokens=2200,
                messages=[
                    cast(
                        ChatCompletionUserMessageParam,
                        {
                        "role": "user",
                        "content": [
                                {"type": "image_url", "image_url": {"url": image_url}},
                                {"type": "text", "text": prompt},
                        ],
                        },
                    )
                ],
                stream_answer=stream_answer,
            )
            return text.strip() or None
        except Exception:
            return None

    def analyze_meal_image_paths(
        self,
        *,
        before_image_path: str,
        after_image_path: str,
    ) -> dict[str, Any] | None:
        if not self.enabled or self.client is None:
            return None

        try:
            before_url = self._image_path_to_data_url(before_image_path)
            after_url = self._image_path_to_data_url(after_image_path)
            prompt = (
                "你会看到同一份餐食的餐前图和餐后图，请比较前后差异，判断用户实际吃掉了什么。"
                "请直接返回 markdown 正文，不要返回 JSON，不要写代码块。"
                "请严格使用下面结构：\n"
                "## 本次用餐分析\n"
                "### 实际吃掉的食物\n"
                "- 食物：米饭 | 重量：约120g | 克数：120\n"
                "- 食物：鸡胸肉 | 重量：约80g | 克数：80\n"
                "### 营养概览\n"
                "- 热量：520 kcal\n"
                "- 蛋白质：28 g\n"
                "- 碳水化合物：56 g\n"
                "- 脂肪：18 g\n"
                "- 膳食纤维：7 g\n"
                "- 钠：980 mg\n"
                "### 餐前餐后对比\n"
                "- 餐前估算：米饭约180g、鸡胸肉约120g\n"
                "- 餐后剩余：米饭约60g、鸡胸肉约40g\n"
                "- 实际摄入：米饭约120g、鸡胸肉约80g\n"
                "### 计算细节\n"
                "- 克数计算：餐前估算克数 - 餐后剩余克数 = 实际摄入克数。\n"
                "- 热量计算：每种食物实际摄入克数 / 100 × 该食物每100g热量，再求和。\n"
                "- 三大营养素计算：每种食物实际摄入克数 / 100 × 该食物每100g蛋白质/碳水/脂肪，再求和。\n"
                "### 简要点评\n"
                "- 用一句话点评这餐实际摄入情况。\n"
                "必须体现前后对比、计算细节和计算逻辑。如果无法完全确定，请给出最合理估算。"
            )
            text = self._complete_chat_with_optional_thinking(
                model=settings.llm_model,
                temperature=0.2,
                max_tokens=2200,
                messages=[
                    cast(
                        ChatCompletionUserMessageParam,
                        {
                        "role": "user",
                        "content": [
                                {"type": "image_url", "image_url": {"url": before_url}},
                                {"type": "image_url", "image_url": {"url": after_url}},
                                {"type": "text", "text": prompt},
                        ],
                        },
                    )
                ],
                stream_answer=False,
            )
            text = (text or "").strip()
            if not text:
                return None

            foods = self._parse_meal_foods_from_markdown(text)
            nutrition = self._parse_meal_nutrition_from_markdown(text)
            if not foods:
                return None
            return {"foods": foods, "nutrition": nutrition, "markdown": text}
        except Exception:
            return None

    def _parse_meal_foods_from_markdown(self, text: str) -> list[dict[str, Any]]:
        foods: list[dict[str, Any]] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith('-'):
                continue
            food_match = re.search("\u98df\u7269[:\uff1a]\s*([^|]+)", stripped)
            weight_match = re.search("\u91cd\u91cf[:\uff1a]\s*([^|]+)", stripped)
            grams_match = re.search("\u514b\u6570[:\uff1a]\s*(\d+)", stripped)
            if not food_match or not grams_match:
                continue
            foods.append(
                {
                    "food_name": food_match.group(1).strip(),
                    "weight_estimate": (weight_match.group(1).strip() if weight_match else f"\u7ea6{grams_match.group(1)}g"),
                    "estimated_grams": int(grams_match.group(1)),
                }
            )
        return foods

    def _parse_meal_nutrition_from_markdown(self, text: str) -> dict[str, Any]:
        patterns = {
            "calories_kcal": "\u70ed\u91cf[:\uff1a]\s*([0-9.]+)\s*kcal",
            "protein_g": "\u86cb\u767d\u8d28[:\uff1a]\s*([0-9.]+)\s*g",
            "carbohydrate_g": "\u78b3\u6c34\u5316\u5408\u7269[:\uff1a]\s*([0-9.]+)\s*g",
            "fat_g": "\u8102\u80aa[:\uff1a]\s*([0-9.]+)\s*g",
            "dietary_fiber_g": "\u81b3\u98df\u7ea4\u7ef4[:\uff1a]\s*([0-9.]+)\s*g",
            "sodium_mg": "\u94a0[:\uff1a]\s*([0-9.]+)\s*mg",
        }
        nutrition: dict[str, Any] = {}
        for key, pattern in patterns.items():
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                nutrition[key] = float(match.group(1))
        return nutrition

    def _image_path_to_data_url(self, image_path: str) -> str:
        path = os.path.abspath(image_path)
        with open(path, "rb") as image_file:
            image_bytes = image_file.read()
        return self._image_bytes_to_data_url(image_bytes, path)

    def _image_bytes_to_data_url(self, image_bytes: bytes, image_name: str) -> str:
        mime_type = mimetypes.guess_type(image_name)[0] or "image/jpeg"
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    def _build_messages(
        self,
        *,
        user_message: str,
        intent: str,
        state: WorkflowState,
        risk: HealthRiskData,
        nutrition: NutritionAnalysisData,
        recipes: list[RecipeMealItem],
        recommendations: list[str],
        fallback_reply: str,
    ) -> list[ChatCompletionSystemMessageParam | ChatCompletionUserMessageParam]:
        context_payload = {
            "intent": intent,
            "user_message": user_message,
            "goal": state.goal,
            "region": "",
            "diet_preference": state.diet_preference,
            "allergy": state.allergy,
            "disease": state.disease,
            "nutrition": nutrition.model_dump(mode="json"),
            "recipes": [item.model_dump(mode="json") for item in recipes],
            "recommendations": recommendations,
            "fallback_reply": fallback_reply,
            "recent_history": self._serialize_recent_history(state),
        }
        system_prompt = (
            "你是健康营养助手的主回复代理。"
            "请用简洁中文回答，并且只使用已提供的画像、用户输入和工作流上下文。"
            "不要编造医疗事实；如果上下文不足，就尽量贴近 fallback_reply。"
            "本产品主要服务食堂场景和普通大众。"
            "优先给出怎么选菜、怎么搭主食、怎么选汤、怎么控制分量这类实用建议。"
            "避免过于学术化的措辞，也不要写得像医学诊断结论。"
        )
        return [
            cast(ChatCompletionSystemMessageParam, {"role": "system", "content": system_prompt}),
            cast(ChatCompletionUserMessageParam, {"role": "user", "content": json.dumps(context_payload, ensure_ascii=False)}),
        ]

    def _serialize_recent_history(self, state: WorkflowState) -> list[dict[str, str]]:
        return [
            {
                "role": item.role,
                "content": item.content,
                "created_at": item.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            }
            for item in state.recent_history[-LLM_HISTORY_LIMIT:]
        ]

    def _extract_pdf_text(self, file_bytes: bytes) -> str:
        try:
            reader = PdfReader(BytesIO(file_bytes))
            parts: list[str] = []
            for page in reader.pages:
                parts.append(page.extract_text() or "")
            return "\n".join(parts).strip()
        except Exception:
            return ""

    def _extract_json_payload(self, content: str) -> dict[str, Any]:
        try:
            return cast(dict[str, Any], json.loads(content))
        except Exception:
            pass
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            try:
                return cast(dict[str, Any], json.loads(content[start : end + 1]))
            except Exception:
                return {}
        return {}

    def _normalize_recipe_item(self, item: Any) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        meal_type = self._stringify_text(item.get("meal_type"))
        dish_name = self._stringify_text(item.get("dish_name"))
        weight = self._normalize_recipe_weight(item.get("weight"))
        calories_kcal = self._normalize_recipe_calories(item.get("calories_kcal"))
        nutrition_analysis = self._normalize_recipe_nutrition_analysis(item.get("nutrition_analysis"))
        cooking_method = self._stringify_text(item.get("cooking_method"))
        if not meal_type or not dish_name or not weight or calories_kcal is None or not nutrition_analysis or not cooking_method:
            return None
        normalized: dict[str, Any] = {
            "meal_type": meal_type,
            "dish_name": dish_name,
            "ingredients": self._normalize_recipe_ingredients(item.get("ingredients")),
            "weight": weight,
            "calories_kcal": calories_kcal,
            "nutrition_analysis": nutrition_analysis,
            "cooking_method": cooking_method,
        }
        day_label = self._stringify_text(item.get("day_label"))
        if day_label:
            normalized["day_label"] = day_label
        return normalized

    def _normalize_routing_intent(self, value: Any) -> WorkflowIntent | None:
        raw = self._stringify_text(value).lower().replace("-", "_").replace(" ", "_")
        alias_map: dict[str, WorkflowIntent] = {
            "report_parsing": "report_parsing",
            "report_parser": "report_parsing",
            "medical_report": "report_parsing",
            "profile_analysis": "profile_analysis",
            "profile": "profile_analysis",
            "health_risk": "health_risk",
            "risk": "health_risk",
            "recipe_generation": "recipe_generation",
            "recipe": "recipe_generation",
            "meal_plan": "recipe_generation",
            "nutrition_analysis": "nutrition_analysis",
            "nutrition": "nutrition_analysis",
            "meal_record": "meal_record",
            "record": "meal_record",
            "diet_history_analysis": "diet_history_analysis",
            "diet_history": "diet_history_analysis",
            "history_analysis": "diet_history_analysis",
            "meal_history": "diet_history_analysis",
            "recommendation": "recommendation",
            "recommend": "recommendation",
        }
        return alias_map.get(raw)

    def _normalize_recipe_ingredients(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [text for item in value if (text := self._stringify_text(item))]
        text = self._stringify_text(value)
        return [text] if text else []

    def _normalize_recipe_weight(self, value: Any) -> str:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return f"约{int(round(float(value)))}g"
        text = self._stringify_text(value)
        if not text:
            return ""
        compact = text.replace(" ", "")
        if any(unit in compact.lower() for unit in ["g", "kg", "ml"]):
            return text
        if compact.replace(".", "", 1).isdigit():
            return f"约{compact}g"
        return text

    def _normalize_recipe_calories(self, value: Any) -> int | None:
        if isinstance(value, bool) or value in (None, ""):
            return None
        if isinstance(value, (int, float)):
            return int(round(float(value)))
        text = "".join(ch for ch in self._stringify_text(value) if ch.isdigit() or ch == ".")
        if not text:
            return None
        try:
            return int(round(float(text)))
        except ValueError:
            return None

    def _normalize_recipe_nutrition_analysis(self, value: Any) -> str:
        if isinstance(value, dict):
            try:
                return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            except Exception:
                return str(value)
        return self._stringify_text(value)

    def _normalize_string_list(self, value: Any) -> list[str]:
        if isinstance(value, list):
            items = [self._stringify_text(item) for item in value]
        else:
            text = self._stringify_text(value)
            items = [segment.strip() for segment in text.replace("，", ",").split(",")] if text else []
        seen: set[str] = set()
        normalized: list[str] = []
        for item in items:
            if item and item not in seen:
                seen.add(item)
                normalized.append(item)
        return normalized

    def _stringify_text(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return f"{value:g}"
        if isinstance(value, (list, tuple)):
            return "，".join(text for item in value if (text := self._stringify_text(item)))
        if isinstance(value, dict):
            try:
                return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            except Exception:
                return str(value).strip()
        return str(value).strip()

    def _fallback_stream(self, fallback_reply: str):
        chunk_size = 24
        for index in range(0, len(fallback_reply), chunk_size):
            yield fallback_reply[index : index + chunk_size]


llm_service = DashScopeLLMService()
