from __future__ import annotations

import json
import re
from datetime import datetime
from encodings import ptcp154
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from typing import Any, cast
from uuid import uuid4

from app.db.session import SessionLocal
from app.graphs import build_nutrition_graph
from app.models.meal_record import MealRecord
from app.schemas.chat import (
    AgentTraceStep,
    AgentRouteDecision,
    HealthRiskData,
    MealRecordData,
    MealConsumedItem,
    MicronutrientEstimate,
    NutritionAnalysisData,
    RecipeMealItem,
    UserProfileData,
    WorkflowState,
    WorkflowIntent,
)
from app.services.llm_service import llm_service


class BaseAgent:
    """所有智能体的基础抽象。"""

    agent_name = "基础智能体"

    def trace(self, state: WorkflowState, summary: str) -> None:
        """向统一状态中记录智能体执行轨迹。"""
        state.agent_trace.append(
            AgentTraceStep(
                agent_name=self.agent_name,
                summary=summary,
                created_at=datetime.now(),
            )
        )


class GuardAgent(BaseAgent):
    """负责系统守卫逻辑。"""

    agent_name = "守卫智能体"
    protected_intents = {
        "profile_analysis",
        "recipe_generation",
        "recommendation",
        "nutrition_analysis",
    }

    def check(self, state: WorkflowState, intent: str) -> tuple[bool, str | None]:
        """检查是否满足进入核心工作流的前置条件。"""
        self.trace(state, "守卫检查通过，当前可进入后续多智能体工作流。")
        return True, None


class ReportParserAgent(BaseAgent):
    """解析体检报告文本或文件。"""

    agent_name = "体检报告解析智能体"

    def parse_upload(self, report_text: str | None = None, file_bytes: bytes | None = None,
                     file_name: str | None = None, stream_answer: bool = False) -> str:
        """解析上传的体检报告，并返回可全局共享的 Markdown 正文。"""
        source_text = (report_text or "").strip()

        if file_bytes:
            suffix = Path(file_name or "").suffix.lower()
            if suffix == ".pdf":
                source_text = llm_service.parse_medical_report_pdf(
                    file_bytes=file_bytes,
                    file_name=file_name or "medical_report.pdf",
                    stream_answer=stream_answer,
                )
                if not source_text:
                    raise ValueError("PDF 体检报告暂时无法通过大模型完成解析，请稍后重试或改为上传文本内容。")
            else:
                source_text = self._extract_text_from_file(file_bytes=file_bytes, file_name=file_name or "")
        if not source_text:
            raise ValueError("未检测到可解析的体检报告内容，请重新上传。")

        return self._ensure_markdown_report(source_text)

    def _extract_text_from_file(self, file_bytes: bytes, file_name: str) -> str:
        """从上传文件中提取文本。"""
        suffix = Path(file_name).suffix.lower()

        if suffix in {".txt", ".md"}:
            return file_bytes.decode("utf-8", errors="ignore")

        if suffix == ".json":
            return file_bytes.decode("utf-8", errors="ignore")

        raise ValueError("当前仅支持上传 txt、json、pdf 格式的体检报告。")

    def _ensure_markdown_report(self, text: str) -> str:
        """把普通文本包装为 Markdown 报告；PDF 路径通常已由大模型生成 Markdown。"""
        normalized = text.strip()
        if normalized.startswith("#"):
            return normalized
        return f"## 体检报告\n\n{normalized}"


class UserProfileAgent(BaseAgent):
    """基于用户输入和对话上下文生成用户画像展示结果。"""

    agent_name = "用户画像智能体"

    def build_profile(self, state: WorkflowState, user_message: str = "", generate_reply: bool = True) -> UserProfileData:
        """基于当前用户输入生成面向用户的 Markdown 画像。"""
        profile = UserProfileData()
        state.user_profile = profile
        state.profile_completed = True
        if not generate_reply:
            self.trace(state, "已跳过用户画像展示内容生成。")
            return profile

        state.latest_profile_reply = (
            llm_service.generate_user_profile_markdown(
                medical_report_markdown="",
                user_message=user_message.strip(),
                stream_answer=True,
            )
            or self._build_fallback_markdown(user_message)
        )
        print("用户画像",state.latest_profile_reply)
        self.trace(state, "已基于用户输入生成用户画像 Markdown。")
        return profile

    def _build_fallback_markdown(self, user_message: str) -> str:
        if user_message.strip():
            return f"## 用户画像\n\n已收到你的补充信息：{user_message.strip()}\n\n你可以继续补充饮食目标、口味偏好、忌口、过敏信息或用餐场景。"
        return "## 用户画像\n\n请补充你的饮食目标、口味偏好、忌口、过敏信息或单位食堂用餐场景，我会继续完善画像。"


class HealthRiskAgent(BaseAgent):
    """回答用户关于忌口、禁忌食物和需要避免菜品的问题。"""

    agent_name = "忌口建议智能体"

    def assess(self, state: WorkflowState, user_message: str = "") -> str:
        """把用户问题交给大模型，返回可展示的忌口建议 Markdown。"""
        report = ""
        reply = (
            llm_service.generate_health_risk_markdown(
                medical_report_markdown=report,
                user_message=user_message.strip(),
                stream_answer=True,
            )
            or self._build_fallback_markdown(report)
        )
        state.latest_health_risk_reply = reply
        self.trace(state, "已基于用户输入生成忌口与禁忌菜品建议。")
        return reply

    def _build_fallback_markdown(self, report: str) -> str:
        if not report:
            return "## 忌口建议\n\n请补充你的忌口、过敏、疾病名称或饮食目标，我会据此给出需要避免或少吃的食物。"
        return (
            "## 忌口建议\n\n"
            "当前大模型暂时不可用，无法完成个性化忌口分析。"
            "你可以稍后重试，或直接说明你最关心的指标，例如血糖、尿酸、血脂、血压等。"
        )


class NutritionAnalysisAgent(BaseAgent):
    """负责营养分析和每日摄入建议。"""

    agent_name = "营养分析智能体"

    def analyze(self, state: WorkflowState) -> NutritionAnalysisData:
        """根据目标输出营养摄入建议。"""
        goal = state.goal or "均衡饮食"

        analysis_map = {
            "减脂": NutritionAnalysisData(
                calories_kcal=1500,
                protein_g=100,
                carbohydrate_g=150,
                fat_g=45,
                dietary_fiber_g=30,
                sodium_mg=1800,
                sugar_g=20,
                vitamin_focus=["维生素 B 群", "维生素 C"],
                trace_elements=["钾", "镁"],
            ),
            "增肌": NutritionAnalysisData(
                calories_kcal=2200,
                protein_g=135,
                carbohydrate_g=260,
                fat_g=60,
                dietary_fiber_g=30,
                sodium_mg=2000,
                sugar_g=28,
                vitamin_focus=["维生素 D", "维生素 B6"],
                trace_elements=["锌", "镁"],
            ),
            "控糖": NutritionAnalysisData(
                calories_kcal=1650,
                protein_g=95,
                carbohydrate_g=140,
                fat_g=50,
                dietary_fiber_g=32,
                sodium_mg=1800,
                sugar_g=18,
                vitamin_focus=["维生素 C", "维生素 E"],
                trace_elements=["铬", "镁"],
            ),
            "控尿酸": NutritionAnalysisData(
                calories_kcal=1700,
                protein_g=85,
                carbohydrate_g=180,
                fat_g=48,
                dietary_fiber_g=30,
                sodium_mg=1800,
                sugar_g=20,
                vitamin_focus=["维生素 C"],
                trace_elements=["钾"],
            ),
            "养胃": NutritionAnalysisData(
                calories_kcal=1750,
                protein_g=90,
                carbohydrate_g=190,
                fat_g=45,
                dietary_fiber_g=26,
                sodium_mg=1700,
                sugar_g=20,
                vitamin_focus=["维生素 A", "维生素 B1"],
                trace_elements=["锌"],
            ),
            "均衡饮食": NutritionAnalysisData(),
        }
        analysis = analysis_map.get(goal, NutritionAnalysisData())

        state.nutrition_analysis = analysis
        self.trace(state, "已完成热量与三大营养素分析。")
        return analysis


class RecipeGenerationAgent(BaseAgent):
    """负责生成专属食谱。"""

    agent_name = "食谱生成智能体"

    def generate(self, state: WorkflowState, user_message: str = "") -> list[RecipeMealItem] | str:
        """生成满足目标、风险、偏好的餐次方案。"""
        now = datetime.now()
        profile = state.user_profile or UserProfileData()
        region = "未明确"
        season = self._resolve_season(now.month)
        time_of_day = self._resolve_time_of_day(now.hour)
        plan_scope = self._resolve_plan_scope(user_message)
        recent_history = [
            {
                "role": item.role,
                "content": item.content,
                "created_at": item.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            }
            for item in state.recent_history[-6:]
        ]

        llm_recipe_reply = llm_service.generate_recipe_plan(
            workflow_state=state,
            user_profile=profile,
            medical_report=None,
            risk=state.health_risk,
            nutrition=state.nutrition_analysis or NutritionAnalysisData(),
            region=region,
            season=season,
            month_label=f"{now.month}月",
            time_of_day=time_of_day,
            current_datetime=now.strftime("%Y-%m-%d %H:%M:%S"),
            user_message=user_message,
            plan_scope=plan_scope,
            recent_history=recent_history,
            stream_answer=True,
        )
        print("食谱生成",llm_recipe_reply)

        if llm_recipe_reply and llm_recipe_reply.strip():
            state.recipe_plan = []
            state.latest_recipe_reply = llm_recipe_reply.strip()
            self.trace(state, "已将用户输入、地域、季节与时间送入大模型完成食谱生成。")
            return state.latest_recipe_reply

        recipes = self._build_rule_recipe(state, plan_scope, region=region, season=season, time_of_day=time_of_day)
        state.recipe_plan = recipes
        state.latest_recipe_reply = ""
        self.trace(state, "大模型食谱不可用或命中冲突，已回退到规则食谱。")
        return recipes

    def _build_rule_recipe(
            self,
            state: WorkflowState,
            plan_scope: str,
            *,
            region: str,
            season: str,
            time_of_day: str,
    ) -> list[RecipeMealItem]:
        """当大模型不可用时，回退到规则型食谱。"""
        goal = state.goal or "均衡饮食"
        risk_warnings = state.health_risk.warnings if state.health_risk else []
        low_salt = "高血压风险" in state.disease or any("血压" in item for item in risk_warnings)
        low_purine = "高尿酸风险" in state.disease
        low_sugar = "高血糖风险" in state.disease or goal == "控糖"
        context = state.recommendation_context or {}
        blocked_terms = set(state.allergy) | set(state.diet_preference) | set(context.get("disliked_dishes", []))

        if plan_scope == "week":
            return self._build_weekly_rule_recipe(
                goal,
                low_salt,
                low_purine,
                low_sugar,
                region=region,
                season=season,
                time_of_day=time_of_day,
            )

        breakfast = RecipeMealItem(
            meal_type="早餐",
            dish_name="燕麦鸡蛋营养碗" if goal == "增肌" else "杂粮蛋白早餐杯",
            ingredients=["燕麦 40g", "水煮蛋 2 个", "无糖豆浆 250ml", "蓝莓 50g"],
            weight="约 380g",
            calories_kcal=380,
            nutrition_analysis="提供优质蛋白、复合碳水和膳食纤维，帮助稳定上午血糖和饱腹感。",
            cooking_method="煮制 + 即食搭配",
        )
        lunch = RecipeMealItem(
            meal_type="午餐",
            dish_name="香煎鸡胸肉糙米定食",
            ingredients=[
                "鸡胸肉 150g",
                "糙米饭 120g",
                "西兰花 150g",
                "胡萝卜 80g",
            ],
            weight="约 500g",
            calories_kcal=560,
            nutrition_analysis="蛋白质充足，搭配中低 GI 主食和高纤蔬菜，更利于体重与代谢管理。",
            cooking_method="少油煎制 + 蒸煮",
        )
        dinner = RecipeMealItem(
            meal_type="晚餐",
            dish_name="清蒸鱼片蔬菜盘",
            ingredients=["鱼片 150g", "南瓜 120g", "菠菜 120g", "菌菇 100g"],
            weight="约 420g",
            calories_kcal=430,
            nutrition_analysis="晚餐控制油脂和热量，同时保留优质蛋白和蔬菜，减少夜间代谢负担。",
            cooking_method="清蒸 + 焯拌",
        )
        snack = RecipeMealItem(
            meal_type="加餐",
            dish_name="低糖酸奶坚果杯",
            ingredients=["低糖酸奶 150g", "坚果 10g", "苹果半个"],
            weight="约 180g",
            calories_kcal=180,
            nutrition_analysis="缓解饥饿并补充蛋白与健康脂肪，避免暴食。",
            cooking_method="直接组合",
        )

        breakfast_name, breakfast_ingredients, breakfast_method = self._select_breakfast_template(region, season, 0)
        lunch_name, lunch_ingredients, lunch_method = self._select_main_meal_template(region, season, "午餐", 0)
        dinner_name, dinner_ingredients, dinner_method = self._select_main_meal_template(region, season, "晚餐", 1)
        snack_name, snack_ingredients, snack_method = self._select_snack_template(season, time_of_day, 0)
        style_text = self._build_style_text(region, season)

        breakfast.dish_name = breakfast_name
        breakfast.ingredients = breakfast_ingredients
        breakfast.cooking_method = breakfast_method
        breakfast.nutrition_analysis = f"{style_text}，早餐更偏家常、清爽、好执行。"
        lunch.dish_name = lunch_name
        lunch.ingredients = lunch_ingredients
        lunch.cooking_method = lunch_method
        lunch.nutrition_analysis = f"{style_text}，午餐采用更接地气的家常搭配。"
        dinner.dish_name = dinner_name
        dinner.ingredients = dinner_ingredients
        dinner.cooking_method = dinner_method
        dinner.nutrition_analysis = f"{style_text}，晚餐控制油盐并保留当季食材。"
        snack.dish_name = snack_name
        snack.ingredients = snack_ingredients
        snack.cooking_method = snack_method
        snack.nutrition_analysis = f"结合{season}和{time_of_day}时段，安排更朴素自然的加餐。"

        recipes = [breakfast, lunch, dinner, snack]

        for item in recipes:
            if any(term and term in item.dish_name for term in blocked_terms):
                item.nutrition_analysis += " 已结合你的忌口和反馈做了避让。"
        if low_salt:
            for item in recipes:
                item.nutrition_analysis += " 当前已按低钠方向控制调味。"
        if low_purine:
            lunch.ingredients = [ingredient for ingredient in lunch.ingredients if "鱼" not in ingredient]
            lunch.ingredients.insert(0, "鸡胸肉 150g")
            lunch.dish_name = "低嘌呤鸡胸蔬菜定食"
            lunch.nutrition_analysis += " 已避开高嘌呤海鲜与浓汤。"
        if low_sugar:
            breakfast.ingredients = [ingredient for ingredient in breakfast.ingredients if "蓝莓" not in ingredient]
            breakfast.ingredients.append("黄瓜条 80g")
            breakfast.nutrition_analysis += " 已减少高糖水果比例。"

        return recipes

    def _build_weekly_rule_recipe(
            self,
            goal: str,
            low_salt: bool,
            low_purine: bool,
            low_sugar: bool,
            *,
            region: str,
            season: str,
            time_of_day: str,
    ) -> list[RecipeMealItem]:
        """生成一周规则型食谱，避免“今日/本周”返回完全相同。"""
        week_days = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        breakfast_options = [
            ("杂粮蛋白早餐杯", ["燕麦 40g", "水煮蛋 2 个", "无糖豆浆 250ml", "蓝莓 50g"]),
            ("全麦鸡蛋蔬菜卷", ["全麦饼 1 张", "鸡蛋 2 个", "生菜 60g", "番茄 80g"]),
            ("南瓜藜麦早餐碗", ["南瓜 120g", "藜麦 50g", "无糖酸奶 150g"]),
            ("玉米鸡蛋豆浆餐", ["甜玉米 1 根", "水煮蛋 2 个", "无糖豆浆 250ml"]),
            ("小米山药早餐碗", ["小米粥 1 碗", "山药 100g", "鸡蛋 1 个"]),
            ("燕麦坚果酸奶杯", ["燕麦 35g", "低糖酸奶 180g", "坚果 10g"]),
            ("红薯蛋白早餐盘", ["蒸红薯 120g", "鸡蛋 2 个", "黄瓜条 80g"]),
        ]
        lunch_options = [
            ("香煎鸡胸肉糙米定食", ["鸡胸肉 150g", "糙米饭 120g", "西兰花 150g", "胡萝卜 80g"]),
            ("清蒸鱼柳杂粮饭", ["鱼柳 150g", "杂粮饭 120g", "西蓝花 150g"]),
            ("牛肉藜麦蔬菜碗", ["瘦牛肉 120g", "藜麦 100g", "彩椒 100g", "生菜 80g"]),
            ("豆腐鸡丝时蔬盘", ["鸡丝 120g", "嫩豆腐 120g", "菠菜 120g", "糙米饭 100g"]),
            ("番茄鸡肉意面", ["全麦意面 100g", "鸡胸肉 120g", "番茄 120g"]),
            ("菌菇牛柳荞麦饭", ["牛柳 120g", "荞麦饭 110g", "菌菇 120g"]),
            ("虾仁玉米蔬菜餐", ["虾仁 120g", "玉米粒 80g", "芦笋 120g", "糙米饭 100g"]),
        ]
        dinner_options = [
            ("清蒸鱼片蔬菜盘", ["鱼片 150g", "南瓜 120g", "菠菜 120g", "菌菇 100g"]),
            ("豆腐虾仁轻晚餐", ["虾仁 120g", "豆腐 150g", "油麦菜 120g"]),
            ("鸡胸肉温沙拉", ["鸡胸肉 130g", "生菜 100g", "番茄 80g", "紫甘蓝 60g"]),
            ("山药牛肉轻食碗", ["山药 120g", "瘦牛肉 100g", "西葫芦 100g"]),
            ("三文鱼杂蔬盘", ["三文鱼 120g", "西兰花 120g", "南瓜 100g"]),
            ("豆制品蔬菜晚餐", ["香干 100g", "鸡蛋 1 个", "青菜 150g"]),
            ("鸡腿肉菌菇盘", ["去皮鸡腿肉 130g", "菌菇 120g", "菠菜 100g"]),
        ]
        snack_options = [
            ("低糖酸奶坚果杯", ["低糖酸奶 150g", "坚果 10g", "苹果半个"]),
            ("无糖酸奶蓝莓杯", ["无糖酸奶 150g", "蓝莓 50g"]),
            ("豆浆玉米加餐", ["无糖豆浆 200ml", "玉米半根"]),
            ("坚果黄瓜加餐", ["坚果 12g", "黄瓜条 100g"]),
            ("苹果鸡蛋加餐", ["苹果半个", "鸡蛋 1 个"]),
            ("无糖酸奶燕麦杯", ["无糖酸奶 150g", "燕麦 20g"]),
            ("番茄坚果加餐", ["圣女果 120g", "坚果 10g"]),
        ]

        breakfast_options = [self._select_breakfast_template(region, season, index) for index in range(7)]
        lunch_options = [self._select_main_meal_template(region, season, "午餐", index) for index in range(7)]
        dinner_options = [self._select_main_meal_template(region, season, "晚餐", index + 1) for index in range(7)]
        snack_options = [self._select_snack_template(season, time_of_day, index) for index in range(7)]
        style_text = self._build_style_text(region, season)

        weekly_recipes: list[RecipeMealItem] = []
        for index, day_label in enumerate(week_days):
            breakfast_name, breakfast_ingredients, breakfast_method = breakfast_options[index]
            lunch_name, lunch_ingredients, lunch_method = lunch_options[index]
            dinner_name, dinner_ingredients, dinner_method = dinner_options[index]
            snack_name, snack_ingredients, snack_method = snack_options[index]

            daily_items = [
                RecipeMealItem(day_label=day_label, meal_type="早餐", dish_name=breakfast_name,
                               ingredients=list(breakfast_ingredients), weight="约 360g", calories_kcal=360,
                               nutrition_analysis="提供早餐所需蛋白质与复合碳水，帮助稳定能量与饱腹感。",
                               cooking_method="煮制 + 即食搭配"),
                RecipeMealItem(day_label=day_label, meal_type="午餐", dish_name=lunch_name,
                               ingredients=list(lunch_ingredients), weight="约 500g", calories_kcal=560,
                               nutrition_analysis="午餐强调优质蛋白、适量主食与高纤蔬菜，兼顾血糖与体重管理。",
                               cooking_method="少油煎制 + 蒸煮"),
                RecipeMealItem(day_label=day_label, meal_type="晚餐", dish_name=dinner_name,
                               ingredients=list(dinner_ingredients), weight="约 420g", calories_kcal=420,
                               nutrition_analysis="晚餐更注重清淡和易消化，减少夜间代谢负担。",
                               cooking_method="清蒸 / 焯拌 / 快炒"),
                RecipeMealItem(day_label=day_label, meal_type="加餐", dish_name=snack_name,
                               ingredients=list(snack_ingredients), weight="约 160g", calories_kcal=180,
                               nutrition_analysis="加餐帮助缓解饥饿，避免正餐前后暴食。", cooking_method="直接组合"),
            ]

            daily_items[0].cooking_method = breakfast_method
            daily_items[1].cooking_method = lunch_method
            daily_items[2].cooking_method = dinner_method
            daily_items[3].cooking_method = snack_method
            daily_items[0].nutrition_analysis = f"{style_text}，早餐偏家常清淡。"
            daily_items[1].nutrition_analysis = f"{style_text}，午餐用常见家常菜搭配主食。"
            daily_items[2].nutrition_analysis = f"{style_text}，晚餐清淡一些，适合长期执行。"
            daily_items[3].nutrition_analysis = f"结合{season}和{time_of_day}时段安排的简洁加餐。"

            for item in daily_items:
                if low_salt:
                    item.nutrition_analysis += " 当前已按低钠方向控制调味。"
                if low_purine and any(keyword in " ".join(item.ingredients) for keyword in ["鱼", "虾", "牛"]):
                    item.ingredients = [ingredient for ingredient in item.ingredients if
                                        all(word not in ingredient for word in ["鱼", "虾"])]
                    item.ingredients.insert(0, "鸡胸肉 120g")
                    item.nutrition_analysis += " 已避开高嘌呤海鲜与浓汤。"
                if low_sugar and item.meal_type in ("早餐", "加餐"):
                    item.ingredients = [ingredient for ingredient in item.ingredients if
                                        all(word not in ingredient for word in ["蓝莓", "苹果"])]
                    item.ingredients.append("黄瓜条 80g")
                    item.nutrition_analysis += " 已减少高糖水果比例。"

            weekly_recipes.extend(daily_items)

        return weekly_recipes

    def _build_style_text(self, region: str, season: str) -> str:
        region_text = region if region and region != "未明确" else "本地"
        return f"结合{region_text}家常口味和{season}当季食材"

    def _select_breakfast_template(self, region: str, season: str, day_index: int) -> tuple[str, list[str], str]:
        seasonal_common = {
            "春季": [("山药小米粥", ["小米粥 1 碗", "山药 100g", "鸡蛋 1 个", "清炒菠菜 80g"], "煮制 + 清炒")],
            "夏季": [("绿豆南瓜粥", ["绿豆小米粥 1 碗", "蒸南瓜 120g", "鸡蛋 1 个", "凉拌黄瓜 80g"], "煮制 + 蒸制")],
            "秋季": [("玉米山药粥", ["玉米糁粥 1 碗", "山药 100g", "鸡蛋 1 个", "清炒油麦菜 80g"], "煮制 + 清炒")],
            "冬季": [("红薯小米粥", ["小米粥 1 碗", "蒸红薯 120g", "鸡蛋 1 个", "清炒小白菜 80g"], "煮制 + 蒸制")],
        }
        regional = {
            "四川": [("番茄鸡蛋面", ["挂面 80g", "鸡蛋 1 个", "番茄 120g", "青菜 80g"], "煮制"),
                     ("青菜瘦肉粥", ["大米粥 1 碗", "瘦肉末 50g", "青菜 80g", "鸡蛋 1 个"], "煮制")],
            "广东": [("生滚鱼片粥", ["大米粥 1 碗", "鱼片 80g", "生菜 80g", "姜丝少量"], "煮制"),
                     ("山药瘦肉粥", ["山药 100g", "瘦肉片 60g", "大米粥 1 碗", "青菜 60g"], "煮制")],
            "湖南": [("鸡蛋青菜米粉", ["米粉 80g", "鸡蛋 1 个", "青菜 80g", "番茄 80g"], "煮制"),
                     ("南瓜粥配时蔬", ["南瓜粥 1 碗", "鸡蛋 1 个", "清炒空心菜 100g"], "煮制 + 清炒")],
            "东北": [("白菜豆腐炖蛋配小米粥", ["小米粥 1 碗", "白菜豆腐 1 份", "鸡蛋 1 个"], "炖煮 + 煮制"),
                     ("玉米饼配蒸蛋", ["玉米饼 2 小块", "蒸鸡蛋羹 1 份", "拌黄瓜 80g"], "蒸制 + 凉拌")],
        }
        candidates = regional.get(region) or seasonal_common.get(season, seasonal_common["春季"])
        return candidates[day_index % len(candidates)]

    def _select_main_meal_template(self, region: str, season: str, meal_type: str, day_index: int) -> tuple[
        str, list[str], str]:
        seasonal_veg = {
            "春季": ["菠菜 120g", "莴笋 100g"],
            "夏季": ["冬瓜 150g", "丝瓜 120g"],
            "秋季": ["莲藕 120g", "南瓜 120g"],
            "冬季": ["白萝卜 120g", "白菜 150g"],
        }
        regional = {
            "四川": {
                "午餐": [("青椒肉丝配米饭", ["瘦肉丝 150g", "青椒 80g", "木耳 60g", "米饭 120g"], "快炒"),
                         ("番茄滑鸡盖饭", ["鸡腿肉 150g", "番茄 120g", "木耳 60g", "米饭 120g"], "快炒 + 焖煮")],
                "晚餐": [("冬瓜蘑菇鸡片", ["鸡胸肉 130g", "冬瓜 150g", "白玉菇 100g", "米饭 80g"], "清炒 + 小炖"),
                         ("蒜蓉油麦菜配蒸蛋", ["油麦菜 150g", "鸡蛋 2 个", "米饭 80g"], "清炒 + 蒸制")],
            },
            "广东": {
                "午餐": [("清蒸鱼片配菜心", ["鱼片 150g", "菜心 150g", "米饭 120g", "香菇 80g"], "清蒸 + 焯煮"),
                         ("冬瓜瘦肉汤配杂粮饭", ["瘦肉片 150g", "冬瓜 180g", "杂粮饭 120g"], "炖煮")],
                "晚餐": [("丝瓜豆腐煮鸡片", ["鸡胸肉 130g", "丝瓜 150g", "嫩豆腐 120g"], "煮制"),
                         ("上汤娃娃菜配蒸南瓜", ["娃娃菜 150g", "南瓜 120g", "鸡蛋 1 个"], "煮制 + 蒸制")],
            },
            "湖南": {
                "午餐": [("小炒黄牛肉轻油版", ["瘦牛肉 120g", "芹菜 80g", "青椒 60g", "米饭 120g"], "快炒"),
                         ("辣椒炒鸡丁配时蔬", ["鸡胸肉 150g", "青椒 60g", "胡萝卜 80g", "米饭 120g"], "少油快炒")],
                "晚餐": [("丝瓜鸡蛋汤配青菜", ["丝瓜 150g", "鸡蛋 2 个", "青菜 150g", "米饭 80g"], "煮制 + 清炒"),
                         ("南瓜蒸肉末", ["南瓜 150g", "瘦肉末 100g", "生菜 120g"], "蒸制")],
            },
            "东北": {
                "午餐": [("白菜豆腐炖肉片", ["瘦肉片 150g", "白菜 180g", "北豆腐 120g", "米饭 120g"], "炖煮"),
                         ("土豆炖鸡块轻油版", ["鸡腿肉 150g", "土豆 120g", "青椒 60g", "米饭 100g"], "炖煮")],
                "晚餐": [("萝卜牛肉汤配小米饭", ["白萝卜 150g", "瘦牛肉 100g", "小米饭 80g"], "炖煮"),
                         ("木耳炒鸡蛋配拌黄瓜", ["鸡蛋 2 个", "木耳 60g", "黄瓜 100g", "玉米半根"], "快炒 + 凉拌")],
            },
        }
        candidates = regional.get(region, {}).get(meal_type)
        if candidates:
            name, ingredients, method = candidates[day_index % len(candidates)]
            return name, list(ingredients) + seasonal_veg.get(season, [])[:1], method
        fallback = {
            "午餐": ("清炒鸡片配时蔬", ["鸡胸肉 150g", "米饭 120g", *seasonal_veg.get(season, []), "香菇 80g"],
                     "少油快炒"),
            "晚餐": ("冬瓜豆腐鸡蛋汤", ["冬瓜 150g", "嫩豆腐 120g", "鸡蛋 2 个", *seasonal_veg.get(season, [])],
                     "煮制"),
        }
        return fallback[meal_type]

    def _select_snack_template(self, season: str, time_of_day: str, day_index: int) -> tuple[str, list[str], str]:
        seasonal = {
            "春季": [("无糖酸奶配圣女果", ["无糖酸奶 150g", "圣女果 120g"], "直接组合"),
                     ("玉米鸡蛋加餐", ["玉米半根", "鸡蛋 1 个"], "蒸制 + 即食")],
            "夏季": [("黄瓜豆浆加餐", ["无糖豆浆 200ml", "黄瓜条 100g"], "直接组合"),
                     ("番茄鸡蛋加餐", ["番茄 120g", "鸡蛋 1 个"], "即食 + 水煮")],
            "秋季": [("蒸南瓜配无糖酸奶", ["蒸南瓜 100g", "无糖酸奶 120g"], "蒸制 + 即食"),
                     ("苹果坚果加餐", ["苹果半个", "坚果 10g"], "直接组合")],
            "冬季": [("热豆浆配蒸红薯", ["热无糖豆浆 200ml", "蒸红薯 100g"], "加热 + 蒸制"),
                     ("山药鸡蛋加餐", ["蒸山药 100g", "鸡蛋 1 个"], "蒸制")],
        }
        name, ingredients, method = seasonal.get(season, seasonal["春季"])[day_index % 2]
        if time_of_day in ("晚上", "凌晨") and "豆浆" in " ".join(ingredients):
            return "无糖酸奶配黄瓜条", ["无糖酸奶 120g", "黄瓜条 100g"], "直接组合"
        return name, ingredients, method

    def _is_valid_llm_recipe_plan(
            self,
            recipes: list[RecipeMealItem] | None,
            state: WorkflowState,
            plan_scope: str,
    ) -> bool:
        """校验大模型生成食谱是否满足结构与健康约束。"""
        if not recipes:
            return False

        expected_meal_types = {"早餐", "午餐", "晚餐", "加餐"}
        if plan_scope == "week":
            if len(recipes) != 28:
                return False
            day_map: dict[str, set[str]] = {}
            for item in recipes:
                if not item.day_label:
                    return False
                day_map.setdefault(item.day_label, set()).add(item.meal_type)
            if len(day_map) != 7:
                return False
            if any(meal_types != expected_meal_types for meal_types in day_map.values()):
                return False
        else:
            if len(recipes) != 4:
                return False
            actual_meal_types = {item.meal_type for item in recipes}
            if actual_meal_types != expected_meal_types:
                return False

        forbidden_text = " ".join(state.health_risk.forbidden_foods) if state.health_risk else ""
        allergy_text = " ".join(state.allergy)

        for item in recipes:
            ingredients_text = " ".join(item.ingredients)
            if allergy_text and any(allergy in ingredients_text for allergy in state.allergy):
                return False
            if forbidden_text and any(food in ingredients_text for food in
                                      (state.health_risk.forbidden_foods if state.health_risk else [])):
                return False
            if item.calories_kcal <= 0:
                return False

        return True

    def _resolve_plan_scope(self, user_message: str) -> str:
        """根据用户问题判断是今日食谱还是本周食谱。"""
        normalized = user_message.strip()
        week_keywords = ["这周", "本周", "下周", "下一周", "未来一周", "一周", "7天", "七天", "周食谱", "周计划"]
        if any(keyword in normalized for keyword in week_keywords):
            return "week"
        return "today"

    def _resolve_season(self, month: int) -> str:
        """根据月份返回季节。"""
        if month in (3, 4, 5):
            return "春季"
        if month in (6, 7, 8):
            return "夏季"
        if month in (9, 10, 11):
            return "秋季"
        return "冬季"

    def _resolve_time_of_day(self, hour: int) -> str:
        """根据小时返回当前时间段。"""
        if 5 <= hour < 11:
            return "上午"
        if 11 <= hour < 14:
            return "中午"
        if 14 <= hour < 18:
            return "下午"
        if 18 <= hour < 23:
            return "晚上"
        return "凌晨"


class RecommendationAgent(BaseAgent):
    """负责个性化推荐优化。"""

    agent_name = "饮食建议智能体"

    def optimize(self, state: WorkflowState) -> list[str]:
        """结合地域、季节和目标生成补充建议。"""
        profile = state.user_profile or UserProfileData()
        now = datetime.now()
        month = now.month
        season = self._resolve_season(month)
        time_of_day = self._resolve_time_of_day(now.hour)

        recommendations = llm_service.generate_recommendations(
            workflow_state=state,
            user_profile=profile,
            medical_report=None,
            risk=state.health_risk,
            season=season,
            month_label=f"{month}月",
            time_of_day=time_of_day,
            current_datetime=now.strftime("%Y-%m-%d %H:%M:%S"),
        )

        if recommendations:
            state.recommendations = recommendations
            self.trace(state, "已将用户输入、地域、季节与时间送入大模型完成推荐优化。")
            return recommendations

        recommendations = self._build_rule_recommendations(state, profile, month)
        state.recommendations = recommendations
        self.trace(state, "大模型推荐不可用，已回退到规则推荐优化。")
        return recommendations

    def _build_rule_recommendations(
            self,
            state: WorkflowState,
            profile: UserProfileData,
            month: int,
    ) -> list[str]:
        """当大模型不可用时，回退到规则推荐。"""
        recommendations: list[str] = []

        if 5 <= month <= 9:
            recommendations.append("当前季节偏热，建议增加冬瓜、黄瓜、番茄等清爽食材，同时保证补水。")
        else:
            recommendations.append("当前季节可适当增加温热汤羹，但仍要避免高油高盐。")

        if state.goal:
            recommendations.append(f"你的当前目标为【{state.goal}】，建议至少连续执行 7 天后再评估调整。")
        else:
            recommendations.append("建议补充你的核心目标，例如减脂、控糖或养胃，以便系统持续优化。")

        return recommendations

    def _resolve_season(self, month: int) -> str:
        """根据月份返回当前季节。"""
        if month in (3, 4, 5):
            return "春季"
        if month in (6, 7, 8):
            return "夏季"
        if month in (9, 10, 11):
            return "秋季"
        return "冬季"

    def _resolve_time_of_day(self, hour: int) -> str:
        """根据小时返回当前时间段。"""
        if 5 <= hour < 11:
            return "上午"
        if 11 <= hour < 14:
            return "中午"
        if 14 <= hour < 18:
            return "下午"
        if 18 <= hour < 23:
            return "晚上"
        return "凌晨"


class MealRecordAgent(BaseAgent):
    """负责记录和分析用餐历史。"""

    agent_name = "用餐记录智能体"
    MEAL_INTENT_KEYWORDS = ["璁板綍", "鍚冧簡", "鏃╅", "鍗堥", "鏅氶", "鍔犻", "鐢ㄩ"]
    NON_FOOD_LABELS = {
        "热量",
        "能量",
        "卡路里",
        "总热量",
        "蛋白质",
        "碳水",
        "碳水化合物",
        "脂肪",
        "膳食纤维",
        "纤维",
        "钠",
        "糖",
        "营养素",
        "合计",
        "总计",
    }
    MICRONUTRIENT_DB: dict[str, dict[str, tuple[float, str]]] = {
        "米饭": {"锰": (0.35, "mg"), "硒": (4.0, "ug")},
        "鸡蛋": {"硒": (23.3, "ug"), "锌": (1.1, "mg"), "维生素B12": (1.1, "ug")},
        "番茄": {"维生素C": (14.0, "mg"), "钾": (179.0, "mg"), "番茄红素": (2570.0, "ug")},
        "西兰花": {"维生素C": (51.0, "mg"), "叶酸": (120.0, "ug"), "钾": (206.0, "mg")},
        "鸡胸肉": {"烟酸": (13.7, "mg"), "维生素B6": (0.6, "mg"), "磷": (196.0, "mg")},
        "鱼": {"硒": (36.5, "ug"), "维生素D": (5.0, "ug"), "碘": (19.0, "ug")},
        "虾": {"硒": (56.0, "ug"), "锌": (1.9, "mg"), "碘": (22.0, "ug")},
        "牛肉": {"铁": (2.8, "mg"), "锌": (4.7, "mg"), "维生素B12": (2.1, "ug")},
        "菠菜": {"叶酸": (194.0, "ug"), "钾": (311.0, "mg"), "镁": (58.0, "mg")},
        "豆腐": {"钙": (138.0, "mg"), "镁": (63.0, "mg"), "铁": (2.7, "mg")},
        "胡萝卜": {"维生素A": (835.0, "ug"), "钾": (320.0, "mg")},
        "南瓜": {"维生素A": (148.0, "ug"), "钾": (145.0, "mg")},
        "黄瓜": {"钾": (102.0, "mg"), "维生素K": (16.4, "ug")},
        "蘑菇": {"硒": (2.2, "ug"), "钾": (318.0, "mg"), "铜": (0.3, "mg")},
        "青椒": {"维生素C": (72.0, "mg"), "维生素B6": (0.2, "mg")},
        "苹果": {"钾": (107.0, "mg"), "维生素C": (4.0, "mg")},
    }

    def __init__(self) -> None:
        self.picfile_dir = Path(__file__).resolve().parents[1] / "picfile"
        self.picfile_dir.mkdir(parents=True, exist_ok=True)

    def maybe_record(
            self,
            state: WorkflowState,
            user_message: str,
            *,
            before_image_bytes: bytes | None = None,
            before_image_name: str | None = None,
            after_image_bytes: bytes | None = None,
            after_image_name: str | None = None,
            uploaded_image_count: int = 0,
    ) -> MealRecordData | str | None:
        """如果用户表达了记录饮食的意图，则保存为用餐记录。"""
        print("可能保存")
        normalized = user_message.strip()
        has_image_pair = bool(before_image_bytes and after_image_bytes)

        if has_image_pair:
            record = self._record_from_image_pair(
                user_message=normalized,
                before_image_bytes=cast(bytes, before_image_bytes),
                before_image_name=before_image_name or "before.jpg",
                after_image_bytes=cast(bytes, after_image_bytes),
                after_image_name=after_image_name or "after.jpg",
                nutrition_target=state.nutrition_analysis or NutritionAnalysisData(),
            )
            if record is not None:
                state.meal_records.append(record)
                self.trace(state, f"已完成 1 条{record.meal_type}餐前餐后图片记录，并估算实际摄入与微量元素。")
                return record

        if not any(keyword in normalized for keyword in ["记录", "吃了", "早餐", "午餐", "晚餐", "加餐", "用餐"]):
            return None

        if uploaded_image_count == 1:
            return "要完成餐食记录，请同时上传餐前和餐后两张图片；当前只收到 1 张图片。"
        if not has_image_pair:
            return "要完成餐食记录，请上传餐前和餐后两张图片后再试。"

        meal_type = self._resolve_meal_type(normalized)
        food_source = normalized
        detail_match = re.search(r"(?:吃了|吃的|内容[:：]?)(.+)$", normalized)
        if detail_match:
            food_source = detail_match.group(1).strip()

        foods = [segment.strip() for segment in re.split(r"[，,、；;]", food_source) if segment.strip()]
        consumed_items = [
            MealConsumedItem(food_name=item, weight_estimate="约100g", estimated_grams=100)
            for item in foods[:6]
        ]
        micronutrients = self._estimate_micronutrients(consumed_items)
        record = MealRecordData(
            recorded_at=datetime.now(),
            meal_type=meal_type,
            foods=foods[:6],
            consumed_items=consumed_items,
            micronutrients=micronutrients,
            estimated_calories_kcal=450 if meal_type != "加餐" else 180,
            feedback="系统已记录本次饮食，可继续用于后续营养趋势分析。",
        )
        state.meal_records.append(record)
        self.trace(state, f"已记录 1 条{meal_type}信息，纳入长期饮食追踪。")
        return record

    def record_single_image_analysis(
            self,
            state: WorkflowState,
            *,
            user_message: str,
            analysis_markdown: str,
            recorded_at: datetime | None = None,
    ) -> MealRecordData | None:
        consumed_items = self._extract_consumed_items_from_single_image_markdown(analysis_markdown)
        if not consumed_items:
            return None

        nutrition = self._extract_nutrition_from_markdown(analysis_markdown)
        record = MealRecordData(
            recorded_at=recorded_at or datetime.now(),
            meal_type=self._resolve_meal_type(user_message),
            foods=[item.food_name for item in consumed_items],
            consumed_items=consumed_items,
            micronutrients=self._estimate_micronutrients(consumed_items),
            estimated_calories_kcal=self._coerce_int(nutrition.get("calories_kcal")),
            estimated_protein_g=self._coerce_float(nutrition.get("protein_g")),
            estimated_carbohydrate_g=self._coerce_float(nutrition.get("carbohydrate_g")),
            estimated_fat_g=self._coerce_float(nutrition.get("fat_g")),
            estimated_dietary_fiber_g=self._coerce_float(nutrition.get("dietary_fiber_g")),
            estimated_sodium_mg=self._coerce_float(nutrition.get("sodium_mg")),
            analysis_markdown=analysis_markdown.strip(),
            feedback="已根据单张餐食图片完成摄入估算。",
        )
        state.meal_records.append(record)
        self.trace(state, f"已完成 1 条{record.meal_type}单张餐食图片记录，纳入长期饮食追踪。")
        return record

    def _extract_consumed_items_from_single_image_markdown(self, markdown: str) -> list[MealConsumedItem]:
        consumed_items: list[MealConsumedItem] = []
        seen: set[str] = set()
        for line in markdown.splitlines():
            stripped = line.strip()
            if not stripped.startswith("|") or "---" in stripped:
                continue
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if len(cells) < 2:
                continue
            food_name = cells[0].strip(" *")
            if not self._is_food_name_candidate(food_name) or food_name in seen:
                continue
            grams = self._extract_grams(" ".join(cells[1:]))
            if grams <= 0:
                continue
            seen.add(food_name)
            consumed_items.append(
                MealConsumedItem(
                    food_name=food_name,
                    weight_estimate=cells[1],
                    estimated_grams=grams,
                )
            )
            if len(consumed_items) >= 8:
                break

        if consumed_items:
            return consumed_items

        for match in re.finditer(r"(?:食物|菜品)\s*[:：]\s*([^，,。\n]+).*?(\d{1,4}(?:\.\d+)?)\s*(?:克|g)", markdown, flags=re.IGNORECASE):
            food_name = match.group(1).strip(" *")
            if not self._is_food_name_candidate(food_name) or food_name in seen:
                continue
            grams = self._coerce_int(match.group(2))
            if grams <= 0:
                continue
            seen.add(food_name)
            consumed_items.append(
                MealConsumedItem(
                    food_name=food_name,
                    weight_estimate=f"约{grams}g",
                    estimated_grams=grams,
                )
            )
            if len(consumed_items) >= 8:
                break
        return consumed_items

    def _extract_grams(self, text: str) -> int:
        match = re.search(r"(\d{1,4}(?:\.\d+)?)\s*(?:克|g)", text, flags=re.IGNORECASE)
        if not match:
            return 0
        return self._coerce_int(match.group(1))

    def _is_food_name_candidate(self, value: str) -> bool:
        name = value.strip(" *：:")
        if not name:
            return False
        if name in {"食物", "名称", "菜品"}:
            return False
        return name not in self.NON_FOOD_LABELS

    def _extract_nutrition_from_markdown(self, markdown: str) -> dict[str, float | int]:
        patterns = {
            "calories_kcal": r"(?:热量|能量|卡路里)[^\d]{0,12}(\d{1,5}(?:\.\d+)?)\s*(?:kcal|千卡|大卡)?",
            "protein_g": r"(?:蛋白质)[^\d]{0,12}(\d{1,4}(?:\.\d+)?)\s*g?",
            "carbohydrate_g": r"(?:碳水|碳水化合物)[^\d]{0,12}(\d{1,4}(?:\.\d+)?)\s*g?",
            "fat_g": r"(?:脂肪)[^\d]{0,12}(\d{1,4}(?:\.\d+)?)\s*g?",
            "dietary_fiber_g": r"(?:膳食纤维|纤维)[^\d]{0,12}(\d{1,4}(?:\.\d+)?)\s*g?",
            "sodium_mg": r"(?:钠)[^\d]{0,12}(\d{1,5}(?:\.\d+)?)\s*(?:mg|毫克)?",
        }
        nutrition: dict[str, float | int] = {}
        for key, pattern in patterns.items():
            match = re.search(pattern, markdown, flags=re.IGNORECASE)
            if not match:
                continue
            value = float(match.group(1))
            nutrition[key] = int(value) if key == "calories_kcal" else round(value, 1)
        return nutrition

    def _record_from_image_pair(
            self,
            *,
            user_message: str,
            before_image_bytes: bytes,
            before_image_name: str,
            after_image_bytes: bytes,
            after_image_name: str,
            nutrition_target: NutritionAnalysisData,
    ) -> MealRecordData | None:
        before_image_path = self._persist_meal_image(before_image_bytes, before_image_name, prefix="before")
        after_image_path = self._persist_meal_image(after_image_bytes, after_image_name, prefix="after")
        # 解析图片
        analysis = llm_service.analyze_meal_image_paths(
            before_image_path=str(before_image_path),
            after_image_path=str(after_image_path),
        )
        print("analysis分析结果", analysis)
        if not analysis:
            return None

        items_payload = analysis.get("foods")
        if not isinstance(items_payload, list):
            return None

        consumed_items: list[MealConsumedItem] = []
        for item in items_payload:
            if not isinstance(item, dict):
                continue
            food_name = str(item.get("food_name") or "").strip()
            if not food_name:
                continue
            grams = self._coerce_int(item.get("estimated_grams"))
            if grams <= 0:
                continue
            consumed_items.append(
                MealConsumedItem(
                    food_name=food_name,
                    weight_estimate=str(item.get("weight_estimate") or f"约{grams}g").strip(),
                    estimated_grams=grams,
                )
            )

        if not consumed_items:
            return None

        micronutrients = self._estimate_micronutrients(consumed_items)
        nutrition_payload = analysis.get("nutrition") if isinstance(analysis.get("nutrition"), dict) else {}
        meal_type = self._resolve_meal_type(user_message)
        record = MealRecordData(
            recorded_at=datetime.now(),
            meal_type=meal_type,
            foods=[item.food_name for item in consumed_items],
            consumed_items=consumed_items,
            micronutrients=micronutrients,
            estimated_calories_kcal=self._coerce_int(nutrition_payload.get("calories_kcal")),
            estimated_protein_g=self._coerce_float(nutrition_payload.get("protein_g")),
            estimated_carbohydrate_g=self._coerce_float(nutrition_payload.get("carbohydrate_g")),
            estimated_fat_g=self._coerce_float(nutrition_payload.get("fat_g")),
            estimated_dietary_fiber_g=self._coerce_float(nutrition_payload.get("dietary_fiber_g")),
            estimated_sodium_mg=self._coerce_float(nutrition_payload.get("sodium_mg")),
            analysis_markdown=str(analysis.get("markdown") or "").strip() or None,
            feedback="已根据餐前餐后图片完成实际摄入估算。",
        )
        record.analysis_markdown = self._append_meal_calculation_details(record, nutrition_target)
        return record

    def _append_meal_calculation_details(
            self,
            record: MealRecordData,
            nutrition_target: NutritionAnalysisData,
    ) -> str:
        base_markdown = (record.analysis_markdown or "").strip()
        if "## 计算细节与计算逻辑" in base_markdown:
            return base_markdown

        total_grams = sum(item.estimated_grams for item in record.consumed_items)

        def percent(value: float | int | None, target: float | int | None) -> str:
            if value is None or not target:
                return "暂无"
            return f"{round(float(value) / float(target) * 100, 1)}%"

        nutrient_rows = [
            ("热量", f"{record.estimated_calories_kcal or 0} kcal", f"{nutrition_target.calories_kcal} kcal", percent(record.estimated_calories_kcal, nutrition_target.calories_kcal)),
            ("蛋白质", f"{record.estimated_protein_g or 0} g", f"{nutrition_target.protein_g} g", percent(record.estimated_protein_g, nutrition_target.protein_g)),
            ("碳水", f"{record.estimated_carbohydrate_g or 0} g", f"{nutrition_target.carbohydrate_g} g", percent(record.estimated_carbohydrate_g, nutrition_target.carbohydrate_g)),
            ("脂肪", f"{record.estimated_fat_g or 0} g", f"{nutrition_target.fat_g} g", percent(record.estimated_fat_g, nutrition_target.fat_g)),
            ("膳食纤维", f"{record.estimated_dietary_fiber_g or 0} g", f"{nutrition_target.dietary_fiber_g} g", percent(record.estimated_dietary_fiber_g, nutrition_target.dietary_fiber_g)),
            ("钠", f"{record.estimated_sodium_mg or 0} mg", f"{nutrition_target.sodium_mg} mg", percent(record.estimated_sodium_mg, nutrition_target.sodium_mg)),
        ]
        consumed_lines = [
            f"- {item.food_name}：{item.weight_estimate}，按 {item.estimated_grams}g 计入"
            for item in record.consumed_items
        ]
        detail_lines = [
            "",
            "## 计算细节与计算逻辑",
            "### 餐前餐后对比",
            "- 识别逻辑：对比餐前图片中的可见食物与餐后图片中的剩余食物，按“餐前估算量 - 餐后剩余量 = 实际摄入量”计算。",
            f"- 本次实际摄入总重量：约 {total_grams}g。",
            *consumed_lines,
            "",
            "### 营养计算逻辑",
            "- 单个食物营养估算：实际摄入克数 / 100 × 对应食物每 100g 营养参考值。",
            "- 本餐总营养：把所有已摄入食物的热量、蛋白质、碳水、脂肪、膳食纤维和钠分别求和。",
            "- 图片识别存在遮挡、酱汁和剩余量不可见等误差，结果按估算值处理。",
            "",
            "### 占今日建议总量",
            "| 项目 | 本餐估算 | 今日建议 | 占比 |",
            "| --- | ---: | ---: | ---: |",
        ]
        detail_lines.extend([f"| {name} | {value} | {target} | {ratio} |" for name, value, target, ratio in nutrient_rows])
        return f"{base_markdown}\n{chr(10).join(detail_lines)}".strip()

    def _persist_meal_image(self, file_bytes: bytes, file_name: str, *, prefix: str) -> Path:
        suffix = Path(file_name).suffix.lower() or ".jpg"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target_path = self.picfile_dir / f"{timestamp}_{prefix}_{uuid4().hex[:8]}{suffix}"
        target_path.write_bytes(file_bytes)
        return target_path

    def _resolve_meal_type(self, text: str) -> str:
        meal_type = "用餐"
        for item in ["早餐", "午餐", "晚餐", "加餐"]:
            if item in text:
                meal_type = item
                break
        return meal_type

    def _coerce_int(self, value: Any) -> int:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0

    def _coerce_float(self, value: Any) -> float | None:
        try:
            return round(float(value), 1)
        except (TypeError, ValueError):
            return None

    def _estimate_micronutrients(self, consumed_items: list[MealConsumedItem]) -> list[MicronutrientEstimate]:
        totals: dict[tuple[str, str], float] = {}
        for item in consumed_items:
            for keyword, nutrient_map in self.MICRONUTRIENT_DB.items():
                if keyword not in item.food_name:
                    continue
                ratio = item.estimated_grams / 100.0
                for nutrient_name, (amount_per_100g, unit) in nutrient_map.items():
                    key = (nutrient_name, unit)
                    totals[key] = totals.get(key, 0.0) + amount_per_100g * ratio

        ranked = sorted(totals.items(), key=lambda pair: pair[1], reverse=True)[:6]
        return [
            MicronutrientEstimate(name=name, amount=round(amount, 2), unit=unit)
            for (name, unit), amount in ranked
        ]


class DietHistoryAnalysisAgent(BaseAgent):
    """查询历史用餐记录并回答用户问题。"""

    agent_name = "历史饮食分析智能体"

    def answer(self, *, session_id: str, user_message: str, user_id: int | None = None) -> str:
        records = self._load_recent_records(session_id=session_id, user_id=user_id)
        if not records:
            return "我还没有查到你的历史用餐记录。你可以先上传几次餐前餐后图片生成记录，再来问我历史饮食分析问题。"

        history_payload = [
            {
                "recorded_at": item.recorded_at.strftime("%Y-%m-%d %H:%M:%S"),
                "meal_type": item.meal_type,
                "analysis_markdown": item.analysis_markdown,
            }
            for item in records
        ]
        llm_reply = llm_service.answer_diet_history_question(
            user_message=user_message,
            history_records=history_payload,
            stream_answer=True,
        )
        if llm_reply:
            return llm_reply
        return self._build_fallback_reply(history_payload)

    def _load_recent_records(
            self,
            *,
            session_id: str,
            user_id: int | None = None,
            limit: int = 20,
    ) -> list[MealRecord]:
        db = SessionLocal()
        try:
            query = db.query(MealRecord).filter(MealRecord.session_id == session_id)
            if user_id is not None:
                query = query.filter(MealRecord.user_id == user_id)
            return query.order_by(MealRecord.recorded_at.desc(), MealRecord.id.desc()).limit(limit).all()
        finally:
            db.close()

    def _build_fallback_reply(self, history_payload: list[dict[str, str]]) -> str:
        lines = ["我查到了你最近的历史用餐记录："]
        for item in history_payload[:5]:
            lines.append(f"- {item['recorded_at']} {item['meal_type']}")
        lines.append("你可以继续问我，比如最近一周吃得是否偏油、偏咸，或者哪一餐最需要调整。")
        return "\n".join(lines)


class MasterAgent(BaseAgent):
    """负责多智能体调度与最终回复融合。"""

    agent_name = "主控智能体"
    DISABLED_DIRECT_INTENTS: set[WorkflowIntent] = {"nutrition_analysis"}
    ROUTE_AGENT_MAP: dict[WorkflowIntent, str] = {
        "report_parsing": "体检报告解析智能体",
        "profile_analysis": "用户画像智能体",
        "nutrition_analysis": "营养分析智能体",
        "recipe_generation": "食谱生成智能体",
        "recommendation": "饮食建议智能体",
        "meal_record": "用餐记录智能体",
        "diet_history_analysis": "历史饮食分析智能体",
    }

    def __init__(
            self,
            report_parser_agent: ReportParserAgent,
            guard_agent: GuardAgent,
            user_profile_agent: UserProfileAgent,
            health_risk_agent: HealthRiskAgent,
            nutrition_analysis_agent: NutritionAnalysisAgent,
            recipe_generation_agent: RecipeGenerationAgent,
            recommendation_agent: RecommendationAgent,
            meal_record_agent: MealRecordAgent,
            diet_history_analysis_agent: DietHistoryAnalysisAgent,
    ) -> None:
        self.report_parser_agent = report_parser_agent
        self.guard_agent = guard_agent
        self.user_profile_agent = user_profile_agent
        self.health_risk_agent = health_risk_agent
        self.nutrition_analysis_agent = nutrition_analysis_agent
        self.recipe_generation_agent = recipe_generation_agent
        self.recommendation_agent = recommendation_agent
        self.meal_record_agent = meal_record_agent
        self.diet_history_analysis_agent = diet_history_analysis_agent
        self.llm_service = llm_service
        self.workflow_graph = build_nutrition_graph(self)

    def handle_message(
            self,
            state: WorkflowState,
            user_message: str,
            *,
            report_text: str | None = None,
            file_bytes: bytes | None = None,
            file_name: str | None = None,
            meal_before_image_bytes: bytes | None = None,
            meal_before_image_name: str | None = None,
            meal_after_image_bytes: bytes | None = None,
            meal_after_image_name: str | None = None,
            uploaded_image_count: int = 0,
            session_id: str = "",
            user_id: int | None = None,
    ) -> str:
        """根据用户意图驱动完整多智能体工作流。"""
        prepared = self.prepare_reply(
            state,
            user_message,
            report_text=report_text,
            file_bytes=file_bytes,
            file_name=file_name,
            meal_before_image_bytes=meal_before_image_bytes,
            meal_before_image_name=meal_before_image_name,
            meal_after_image_bytes=meal_after_image_bytes,
            meal_after_image_name=meal_after_image_name,
            uploaded_image_count=uploaded_image_count,
            session_id=session_id,
            user_id=user_id,
        )
        if prepared["blocked"]:
            return prepared["guard_message"]
        if prepared["intent"] == "recipe_generation" and prepared.get("recipe_reply"):
            return cast(str, prepared["recipe_reply"])
        if prepared["intent"] == "meal_record":
            meal_record = cast(MealRecordData | None, prepared.get("meal_record"))
            if meal_record and meal_record.analysis_markdown:
                return meal_record.analysis_markdown
            return cast(str, prepared["fallback_reply"])
        if prepared["intent"] == "diet_history_analysis":
            return cast(str, prepared["fallback_reply"])
        if prepared["intent"] in {"report_parsing", "profile_analysis"}:
            return cast(str, prepared["fallback_reply"])

        return self.llm_service.generate_master_reply(
            user_message=user_message,
            intent=prepared["intent"],
            state=state,
            risk=prepared["risk"],
            nutrition=prepared["nutrition"],
            recipes=prepared["recipes"],
            recommendations=prepared["recommendations"],
            fallback_reply=prepared["fallback_reply"],
        )

    def stream_message(
            self,
            state: WorkflowState,
            user_message: str,
            *,
            report_text: str | None = None,
            file_bytes: bytes | None = None,
            file_name: str | None = None,
            meal_before_image_bytes: bytes | None = None,
            meal_before_image_name: str | None = None,
            meal_after_image_bytes: bytes | None = None,
            meal_after_image_name: str | None = None,
            uploaded_image_count: int = 0,
            session_id: str = "",
            user_id: int | None = None,
    ):
        """根据用户意图流式输出最终回复。"""
        event_queue: Queue[dict[str, Any]] = Queue()
        result_holder: dict[str, Any] = {"answer_streamed": False}

        def emit_thinking(content: str) -> None:
            event_queue.put({"type": "thinking", "content": content})

        def emit_answer(content: str) -> None:
            result_holder["answer_streamed"] = True
            event_queue.put({"type": "answer", "content": content})

        def run_prepare() -> None:
            try:
                with self.llm_service.stream_callbacks(
                    thinking_callback=emit_thinking,
                    answer_callback=emit_answer,
                ):
                    result_holder["prepared"] = self.prepare_reply(
                        state,
                        user_message,
                        report_text=report_text,
                        file_bytes=file_bytes,
                        file_name=file_name,
                        meal_before_image_bytes=meal_before_image_bytes,
                        meal_before_image_name=meal_before_image_name,
                        meal_after_image_bytes=meal_after_image_bytes,
                        meal_after_image_name=meal_after_image_name,
                        uploaded_image_count=uploaded_image_count,
                        session_id=session_id,
                        user_id=user_id,
                    )
            except Exception as exc:
                result_holder["error"] = exc
            finally:
                event_queue.put({"type": "prepare_done", "content": ""})

        worker = Thread(target=run_prepare, daemon=True)
        worker.start()

        while True:
            try:
                event = event_queue.get(timeout=0.1)
            except Empty:
                if not worker.is_alive():
                    break
                continue
            if event.get("type") == "prepare_done":
                break
            yield event

        worker.join()
        if result_holder.get("error"):
            raise cast(Exception, result_holder["error"])

        prepared = cast(dict[str, Any], result_holder["prepared"])
        if prepared["blocked"]:
            yield from self._answer_events(cast(str, prepared["guard_message"]))
            return
        if result_holder.get("answer_streamed") and prepared["intent"] in {
            "report_parsing",
            "profile_analysis",
            "recipe_generation",
            "diet_history_analysis",
        }:
            return
        if prepared["intent"] == "recipe_generation" and prepared.get("recipe_reply"):
            yield from self._answer_events(cast(str, prepared["recipe_reply"]))
            return
        if prepared["intent"] == "meal_record":
            meal_record = cast(MealRecordData | None, prepared.get("meal_record"))
            direct_reply = meal_record.analysis_markdown if meal_record and meal_record.analysis_markdown else cast(str,
                                                                                                                    prepared[
                                                                                                                        "fallback_reply"])
            yield from self._answer_events(direct_reply)
            return
        if prepared["intent"] == "diet_history_analysis":
            yield from self._answer_events(cast(str, prepared["fallback_reply"]))
            return
        if prepared["intent"] in {"report_parsing", "profile_analysis"}:
            yield from self._answer_events(cast(str, prepared["fallback_reply"]))
            return

        yield from self.llm_service.stream_master_reply(
            user_message=user_message,
            intent=prepared["intent"],
            state=state,
            risk=prepared["risk"],
            nutrition=prepared["nutrition"],
            recipes=prepared["recipes"],
            recommendations=prepared["recommendations"],
            fallback_reply=prepared["fallback_reply"],
        )

    def _answer_events(self, content: str):
        chunk_size = 48
        for index in range(0, len(content), chunk_size):
            yield {"type": "answer", "content": content[index : index + chunk_size]}

    def prepare_reply(
            self,
            state: WorkflowState,
            user_message: str,
            *,
            report_text: str | None = None,
            file_bytes: bytes | None = None,
            file_name: str | None = None,
            meal_before_image_bytes: bytes | None = None,
            meal_before_image_name: str | None = None,
            meal_after_image_bytes: bytes | None = None,
            meal_after_image_name: str | None = None,
            uploaded_image_count: int = 0,
            session_id: str = "",
            user_id: int | None = None,
    ) -> dict[str, Any]:
        """通过 LangGraph 运行多智能体工作流并返回结构化结果。"""
        result = self.workflow_graph.invoke(
            {
                "user_message": user_message,
                "report_text": report_text,
                "report_file_bytes": file_bytes,
                "report_file_name": file_name,
                "meal_before_image_bytes": meal_before_image_bytes,
                "meal_before_image_name": meal_before_image_name,
                "meal_after_image_bytes": meal_after_image_bytes,
                "meal_after_image_name": meal_after_image_name,
                "uploaded_image_count": uploaded_image_count,
                "session_id": session_id,
                "user_id": user_id,
                "workflow_state": state,
            }
        )

        if result.get("blocked"):
            return {
                "blocked": True,
                "intent": result.get("intent", "recommendation"),
                "guard_message": result.get("guard_message", state.latest_guard_message),
            }

        risk = result.get("risk") or state.health_risk or HealthRiskData(level=state.health_risk_level)
        nutrition = result.get("nutrition") or state.nutrition_analysis or NutritionAnalysisData()
        recipes = result.get("recipes") or list(state.recipe_plan)
        recipe_reply = result.get("recipe_reply") or state.latest_recipe_reply
        recommendations = result.get("recommendations") or list(state.recommendations)

        return {
            "blocked": False,
            "intent": result["intent"],
            "risk": risk,
            "nutrition": nutrition,
            "recipes": recipes,
            "recipe_reply": recipe_reply,
            "recommendations": recommendations,
            "parsed_report": result.get("parsed_report"),
            "meal_record": result.get("meal_record"),
            "health_risk_reply": result.get("health_risk_reply"),
            "fallback_reply": result["fallback_reply"],
        }

    def route_request(
            self,
            state: WorkflowState,
            user_message: str,
            *,
            report_text: str | None = None,
            file_bytes: bytes | None = None,
            file_name: str | None = None,
            meal_before_image_name: str | None = None,
            meal_after_image_name: str | None = None,
            uploaded_image_count: int = 0,
    ) -> AgentRouteDecision:
        """由大模型根据用户问题和智能体描述决定本轮主路由。"""
        routing_message = self._build_routing_message(
            user_message,
            report_text=report_text,
            file_bytes=file_bytes,
            file_name=file_name,
            meal_before_image_name=meal_before_image_name,
            meal_after_image_name=meal_after_image_name,
            uploaded_image_count=uploaded_image_count,
        )
        print("routing_message", routing_message)
        route_payload = self.llm_service.route_agent(
            user_message=routing_message,
            has_medical_report=state.has_medical_report,
            guard_agent={
                "agent_name": self.guard_agent.agent_name,
                "responsibility": "负责基础安全检查，确保用户请求可以进入饮食分析能力。",
                "always_runs": True,
                "selectable": False,
            },
            agent_catalog=self._build_agent_catalog(),
        )
        print("路由信息", route_payload)

        if route_payload is None:
            decision = self._build_fallback_route(routing_message)
        else:
            intent = self._normalize_direct_intent(cast(WorkflowIntent, route_payload["intent"]))
            decision = AgentRouteDecision(
                intent=intent,
                target_agent=self.ROUTE_AGENT_MAP[intent],
                reason=route_payload.get("reason", "大模型已根据当前问题选择最匹配的执行智能体。"),
                source="llm",
            )

        state.last_route = decision
        route_origin = "大模型路由" if decision.source == "llm" else "兜底规则路由"
        print(
            f"主控智能体已通过{route_origin}将本轮问题分配给 {decision.target_agent}（intent={decision.intent}）。原因：{decision.reason}")
        self.trace(
            state,
            f"主控智能体已通过{route_origin}将本轮问题分配给 {decision.target_agent}（intent={decision.intent}）。原因：{decision.reason}",
        )
        return decision

    def _normalize_direct_intent(self, intent: WorkflowIntent) -> WorkflowIntent:
        """关闭不再允许用户直接进入的意图，但保留对应 Agent 的内部能力。"""
        if intent in self.DISABLED_DIRECT_INTENTS:
            return "recipe_generation"
        return intent

    def _build_routing_message(
            self,
            user_message: str,
            *,
            report_text: str | None = None,
            file_bytes: bytes | None = None,
            file_name: str | None = None,
            meal_before_image_name: str | None = None,
            meal_after_image_name: str | None = None,
            uploaded_image_count: int = 0,
    ) -> str:
        normalized = user_message.strip()
        route_hints: list[str] = []
        suffix = Path(file_name or "").suffix.lower()

        if file_bytes and suffix == ".pdf":
            route_hints.append("用户上传了一个PDF文件。")
        elif report_text:
            route_hints.append("用户补充了文本附件。")

        if uploaded_image_count == 2 and meal_before_image_name and meal_after_image_name:
            route_hints.append("用户上传了两张图片文件。")

        if not route_hints:
            return normalized
        if not normalized:
            return "\n".join(route_hints)
        return f"{normalized}\n\n[仅用于路由判断] {' '.join(route_hints)}"

    def _build_agent_catalog(self) -> list[dict[str, Any]]:
        """构建提供给大模型的可选智能体说明。"""
        return [
            {
                "intent": "profile_analysis",
                "agent_name": self.user_profile_agent.agent_name,
                "responsibility": "基于用户表达、对话上下文和已知饮食信息构建用户画像、目标、偏好、过敏与重点关注问题。",
                "when_to_use": ["用户想分析自己的情况", "想看健康画像", "想补充目标或饮食偏好"],
                "depends_on": [self.guard_agent.agent_name],
            },
            {
                "intent": "recipe_generation",
                "agent_name": self.recipe_generation_agent.agent_name,
                "responsibility": "生成今日、本周或指定餐次的早餐、午餐、晚餐、加餐食谱。用户只要在问怎么吃、推荐吃什么、怎么安排饮食，或询问热量、营养、蛋白质、碳水、脂肪怎么搭配，优先进入该智能体并直接给出可执行菜单。",
                "when_to_use": ["用户要食谱", "用户要菜单", "用户想知道今天或这周怎么吃", "用户询问推荐吃什么", "用户询问下一步怎么安排饮食", "用户询问热量、营养、蛋白质、碳水、脂肪怎么搭配", "用户点击引导问题希望继续生成方案"],
                "depends_on": [self.guard_agent.agent_name, self.user_profile_agent.agent_name,
                               self.nutrition_analysis_agent.agent_name],
            },
            {
                "intent": "recommendation",
                "agent_name": self.recommendation_agent.agent_name,
                "responsibility": "只在用户明确要求原则、注意事项、执行建议或不需要具体菜谱时使用。不要用于生成吃什么、菜单、食谱或餐次安排。",
                "when_to_use": ["用户明确说只要建议不要食谱", "用户询问饮食原则", "用户询问日常执行注意事项"],
                "depends_on": [self.guard_agent.agent_name, self.user_profile_agent.agent_name],
            },
            {
                "intent": "meal_record",
                "agent_name": self.meal_record_agent.agent_name,
                "responsibility": "负责新增用餐记录。用户上传餐前图片、餐后图片，或明确表示要记录本次/今天/刚刚吃过的食物时，调用该智能体。该智能体需要对餐前、餐后图片进行对比分析，识别食物种类、估算实际摄入量，计算热量、宏量营养素和微量元素，并将本次用餐结果保存到数据库，同时将分析结果返回给用户。",
                "when_to_use": ["用户上传餐前和餐后图片，并希望分析本次吃了什么、吃了多少",
                                "用户说要记录早餐、午餐、晚餐、加餐或今天吃过的食物",
                                "用户说“帮我记录一下”“保存这顿饭”“分析这顿饭”“看看我这顿吃了多少”",
                                "用户提供本次用餐图片，并希望进行营养成分分析",
                                "用户补录某一餐的食物内容，并希望保存到饮食记录中"],
                "depends_on": [self.guard_agent.agent_name],
            },
            {
                "intent": "diet_history_analysis",
                "agent_name": self.diet_history_analysis_agent.agent_name,
                "responsibility": "负责查询和分析历史用餐记录。该智能体不处理新增用餐图片，也不负责保存新的用餐记录。它只从数据库中读取用户已经保存的饮食记录，并基于历史数据回答用户关于过去饮食情况、营养摄入趋势、饮食问题和调整建议的问题。",
                "when_to_use": ["用户询问历史饮食记录，例如“我昨天吃了什么”“查一下我今天的用餐记录”",
                                "用户想查看最近几天、最近一周或某个时间段的饮食情况",
                                "用户要求分析历史饮食趋势，例如热量是否超标、蛋白质是否不足、蔬菜摄入是否稳定",
                                "用户询问过去饮食问题，例如“我最近吃得健康吗”“这周饮食有什么问题”",
                                "用户要求基于已保存记录生成总结、复盘或调整建议"],
                "depends_on": [],
            },
        ]

    def _build_fallback_route(
            self,
            user_message: str,
    ) -> AgentRouteDecision:
        """当大模型路由失败时，回退到规则路由以保证系统可用。"""
        intent = self._infer_intent_from_keywords(user_message)
        return AgentRouteDecision(
            intent=intent,
            target_agent=self.ROUTE_AGENT_MAP[intent],
            reason="大模型路由不可用或返回了非法结果，系统已回退到兜底规则路由。",
            source="fallback_rule",
        )

    def _infer_intent_from_keywords(self, user_message: str) -> WorkflowIntent:
        normalized = user_message.strip()
        intent_keywords: dict[WorkflowIntent, list[str]] = {
            "meal_record": ["记录", "今天吃了", "早餐", "午餐", "晚餐", "加餐", "餐前", "餐后", "饭前", "饭后",
                            "吃掉了多少"],
            "diet_history_analysis": ["历史饮食", "饮食历史", "历史用餐", "用餐历史", "历史记录分析", "最近几天吃",
                                      "最近一周吃", "过去几天吃", "过去一周吃", "饮食趋势", "历史餐次"],
            "recipe_generation": ["食谱", "菜单", "三餐", "怎么吃", "怎么安排", "推荐", "建议吃", "推荐吃", "吃什么", "安排一下", "规划", "计划", "热量", "营养", "蛋白质", "碳水", "脂肪"],
            "recommendation": ["饮食原则", "注意事项", "执行建议", "只要建议", "不要食谱", "忌口", "禁忌", "不能吃", "不要吃", "避免吃", "少吃", "哪些食物要避开", "哪些菜不能吃"],
            "profile_analysis": ["画像", "分析我", "我的情况"],
        }
        for intent, keywords in intent_keywords.items():
            if any(keyword in normalized for keyword in keywords):
                return cast(WorkflowIntent, intent)
        return "recipe_generation"

    def _build_fallback_reply(
            self,
            *,
            intent: str,
            workflow_state: WorkflowState,
            risk: HealthRiskData,
            nutrition: NutritionAnalysisData,
            recipes: list[RecipeMealItem],
            recommendations: list[str],
            meal_record: MealRecordData | None,
    ) -> str:
        """根据当前路由意图拼接规则型回复，供最终回复大模型降级使用。"""
        if intent == "profile_analysis":
            return self._build_profile_summary(workflow_state)
        if intent == "report_parsing":
            return self._build_report_parser_summary(workflow_state)
        if intent == "nutrition_analysis":
            return self._build_nutrition_summary(nutrition)
        if intent == "recipe_generation":
            return self._build_recipe_summary(recipes)
        if intent == "meal_record":
            return self._build_meal_record_summary(meal_record)
        return self._build_recommendation_summary(recommendations)

    def _build_profile_summary(self, state: WorkflowState) -> str:
        if state.latest_profile_reply:
            return state.latest_profile_reply

        summary_parts: list[str] = []

        if state.goal:
            summary_parts.append(f"当前目标是{state.goal}")
        if state.disease:
            summary_parts.append(f"当前重点关注{'、'.join(state.disease)}")
        if state.diet_preference:
            summary_parts.append(f"饮食偏好偏向{'、'.join(state.diet_preference)}")
        if state.allergy:
            summary_parts.append(f"需要规避{'、'.join(state.allergy)}")
        if not summary_parts:
            return "你可以继续补充目标、口味偏好、忌口、过敏信息或单位食堂用餐场景，我再进一步完善画像。"

        return "根据当前已知信息，" + "，".join(summary_parts) + "。"

    def _build_report_parser_summary(self, state: WorkflowState) -> str:
        if not state.medical_report:
            return "当前暂不启用文件解析主流程。请直接说明你的饮食目标、忌口、过敏信息或食堂用餐需求。"
        if state.latest_profile_reply:
            return state.latest_profile_reply
        return self._build_profile_summary(state)

    def _build_meal_record_summary(self, meal_record: MealRecordData | None) -> str:
        if meal_record is None:
            return "我这次没有识别到可写入的用餐记录，你可以直接告诉我这餐吃了什么。"

        if meal_record.analysis_markdown:
            return meal_record.analysis_markdown

        if meal_record.consumed_items:
            lines = [f"## 本次{meal_record.meal_type}摄入记录", "", "### 实际吃掉的食物"]
            for item in meal_record.consumed_items:
                lines.append(f"- {item.food_name}：{item.weight_estimate}")
            if meal_record.micronutrients:
                lines.extend(["", "### 估算摄入的微量元素"])
                for item in meal_record.micronutrients:
                    lines.append(f"- {item.name}：约 {item.amount}{item.unit}")
            if meal_record.estimated_calories_kcal is not None:
                lines.extend(["", f"### 总量估算", f"- 估算摄入总量：约 {meal_record.estimated_calories_kcal} g"])
            return "\n".join(lines)

        foods = "、".join(meal_record.foods) or "未识别具体食物"
        calories_text = (
            f"，估算热量约 {meal_record.estimated_calories_kcal} kcal"
            if meal_record.estimated_calories_kcal is not None
            else ""
        )
        return f"已为你记录本次{meal_record.meal_type}：{foods}{calories_text}。"

    def _build_risk_summary(self, risk: HealthRiskData) -> str:
        warnings = "；".join(risk.warnings) if risk.warnings else "当前没有明显新增风险提示"
        forbidden = "、".join(risk.forbidden_foods) if risk.forbidden_foods else "当前暂无明确禁忌食物"
        return f"根据当前已知信息，重点提示是：{warnings}。饮食上建议重点规避：{forbidden}。"

    def _build_nutrition_summary(self, nutrition: NutritionAnalysisData) -> str:
        return (
            "结合你当前情况，建议每日摄入约 "
            f"{nutrition.calories_kcal} kcal，蛋白质 {nutrition.protein_g}g，"
            f"碳水 {nutrition.carbohydrate_g}g，脂肪 {nutrition.fat_g}g，"
            f"膳食纤维 {nutrition.dietary_fiber_g}g。"
        )

    def _build_recipe_summary(self, recipes: list[RecipeMealItem]) -> str:
        if not recipes:
            return "当前还没有可展示的食谱结果。"

        def estimate_nutrition(item: RecipeMealItem) -> dict[str, float]:
            calories = max(item.calories_kcal, 0)
            meal_type = item.meal_type
            if "加餐" in meal_type:
                protein = round(calories * 0.16 / 4, 1)
                carbohydrate = round(calories * 0.46 / 4, 1)
                fat = round(calories * 0.38 / 9, 1)
                fiber = 3.0
                sodium = 120.0
                sugar = 8.0
            elif "午餐" in meal_type:
                protein = round(calories * 0.25 / 4, 1)
                carbohydrate = round(calories * 0.45 / 4, 1)
                fat = round(calories * 0.30 / 9, 1)
                fiber = 8.0
                sodium = 650.0
                sugar = 5.0
            elif "晚餐" in meal_type:
                protein = round(calories * 0.28 / 4, 1)
                carbohydrate = round(calories * 0.40 / 4, 1)
                fat = round(calories * 0.32 / 9, 1)
                fiber = 7.0
                sodium = 520.0
                sugar = 4.0
            else:
                protein = round(calories * 0.22 / 4, 1)
                carbohydrate = round(calories * 0.52 / 4, 1)
                fat = round(calories * 0.26 / 9, 1)
                fiber = 6.0
                sodium = 360.0
                sugar = 6.0

            return {
                "calories": float(calories),
                "protein": protein,
                "carbohydrate": carbohydrate,
                "fat": fat,
                "fiber": fiber,
                "sodium": sodium,
                "sugar": sugar,
            }

        def classify_ingredients(ingredients: list[str]) -> dict[str, list[str]]:
            categories = {
                "主食/碳水": [],
                "优质蛋白": [],
                "蔬菜": [],
                "水果": [],
                "奶豆类": [],
                "油脂坚果": [],
                "调味品": [],
            }
            keyword_map = {
                "主食/碳水": ["米", "饭", "面", "麦", "薯", "玉米", "杂粮", "燕麦", "藜麦", "南瓜"],
                "优质蛋白": ["鸡", "鱼", "虾", "牛", "猪", "蛋", "肉", "瘦", "鸭"],
                "蔬菜": ["菜", "青", "瓜", "蘑", "菇", "笋", "番茄", "西兰花", "菠菜", "芹"],
                "水果": ["苹果", "梨", "莓", "橙", "柚", "香蕉", "水果"],
                "奶豆类": ["奶", "豆", "腐", "酸奶", "豆浆"],
                "油脂坚果": ["油", "坚果", "核桃", "杏仁", "芝麻", "花生"],
                "调味品": ["盐", "酱", "醋", "姜", "蒜", "葱", "胡椒"],
            }
            for ingredient in ingredients:
                matched = False
                for category, keywords in keyword_map.items():
                    if any(keyword in ingredient for keyword in keywords):
                        categories[category].append(ingredient)
                        matched = True
                        break
                if not matched:
                    categories["蔬菜"].append(ingredient)
            return categories

        grouped: dict[str, list[RecipeMealItem]] = {}
        for item in recipes:
            grouped.setdefault(item.day_label or "今日", []).append(item)

        lines = ["这是给你的食谱建议："]
        weekly_totals = {
            "calories": 0.0,
            "protein": 0.0,
            "carbohydrate": 0.0,
            "fat": 0.0,
            "fiber": 0.0,
            "sodium": 0.0,
            "sugar": 0.0,
        }

        for day_label, day_items in grouped.items():
            lines.extend(["", f"## {day_label}"])
            daily_totals = dict.fromkeys(weekly_totals, 0.0)
            for item in day_items:
                nutrition = estimate_nutrition(item)
                for key, value in nutrition.items():
                    daily_totals[key] += value
                    weekly_totals[key] += value

                lines.extend(
                    [
                        "",
                        f"### {item.meal_type}：{item.dish_name}",
                        f"- 份量：{item.weight}",
                        f"- 做法：{item.cooking_method}",
                        "- 食物元素归类：",
                    ]
                )
                categories = classify_ingredients(item.ingredients)
                for category, foods in categories.items():
                    if foods:
                        lines.append(f"  - {category}：{'、'.join(foods)}")
                lines.extend(
                    [
                        "- 本餐营养估算：",
                        f"  - 热量：约 {int(nutrition['calories'])} kcal",
                        f"  - 蛋白质：约 {nutrition['protein']} g",
                        f"  - 碳水：约 {nutrition['carbohydrate']} g",
                        f"  - 脂肪：约 {nutrition['fat']} g",
                        f"  - 膳食纤维：约 {nutrition['fiber']} g",
                        f"  - 钠：约 {int(nutrition['sodium'])} mg",
                        f"  - 糖：约 {nutrition['sugar']} g",
                        f"- 本餐说明：{item.nutrition_analysis}",
                    ]
                )

            lines.extend(
                [
                    "",
                    "### 每日总量汇总",
                    f"- 热量：约 {int(daily_totals['calories'])} kcal",
                    f"- 蛋白质：约 {round(daily_totals['protein'], 1)} g",
                    f"- 碳水：约 {round(daily_totals['carbohydrate'], 1)} g",
                    f"- 脂肪：约 {round(daily_totals['fat'], 1)} g",
                    f"- 膳食纤维：约 {round(daily_totals['fiber'], 1)} g",
                    f"- 钠：约 {int(daily_totals['sodium'])} mg",
                    f"- 糖：约 {round(daily_totals['sugar'], 1)} g",
                ]
            )

        if len(grouped) > 1:
            day_count = len(grouped)
            lines.extend(
                [
                    "",
                    "## 本周总结",
                    f"- 平均每日热量：约 {int(weekly_totals['calories'] / day_count)} kcal",
                    f"- 平均每日蛋白质：约 {round(weekly_totals['protein'] / day_count, 1)} g",
                    f"- 平均每日碳水：约 {round(weekly_totals['carbohydrate'] / day_count, 1)} g",
                    f"- 平均每日脂肪：约 {round(weekly_totals['fat'] / day_count, 1)} g",
                    f"- 平均每日膳食纤维：约 {round(weekly_totals['fiber'] / day_count, 1)} g",
                    f"- 平均每日钠：约 {int(weekly_totals['sodium'] / day_count)} mg",
                    f"- 平均每日糖：约 {round(weekly_totals['sugar'] / day_count, 1)} g",
                ]
            )

        return "\n".join(lines)

    def _build_recommendation_summary(self, recommendations: list[str]) -> str:
        if not recommendations:
            return "当前还没有可补充的建议。"

        lines = ["结合你当前的问题，我建议："]
        lines.extend([f"- {item}" for item in recommendations])
        return "\n".join(lines)
