from __future__ import annotations

from typing import Any, cast

from langgraph.graph import END, StateGraph

from app.graphs.state import GraphState
from app.schemas.chat import HealthRiskData, NutritionAnalysisData


def build_nutrition_graph(master_agent: Any):
    """基于 LangGraph 编排多智能体营养工作流。"""

    def infer_intent_node(state):
        workflow_state = state["workflow_state"]
        route = master_agent.route_request(
            workflow_state,
            state["user_message"],
            report_text=state.get("report_text"),
            file_bytes=state.get("report_file_bytes"),
            file_name=state.get("report_file_name"),
            meal_before_image_name=state.get("meal_before_image_name"),
            meal_after_image_name=state.get("meal_after_image_name"),
            uploaded_image_count=state.get("uploaded_image_count", 0),
        )
        return {
            "workflow_state": workflow_state,
            "intent": route.intent,
            "target_agent": route.target_agent,
            "route_reason": route.reason,
            "route_source": route.source,
        }

    def report_parser_node(state):
        workflow_state = state["workflow_state"]
        has_report_text = bool((state.get("report_text") or "").strip())
        has_report_file = bool(state.get("report_file_bytes"))
        if not has_report_text and not has_report_file:
            master_agent.report_parser_agent.trace(workflow_state, "检测到用户希望解析体检报告，但当前消息未携带可解析的报告文件或文本。")
            return {
                "workflow_state": workflow_state,
                "parsed_report": None,
                "report_missing_file": True,
            }

        parsed_report = master_agent.report_parser_agent.parse_upload(
            report_text=state.get("report_text"),
            file_bytes=state.get("report_file_bytes"),
            file_name=state.get("report_file_name"),
        )
        master_agent.report_parser_agent.trace(workflow_state, "已完成体检报告解析，并写入当前会话健康档案。")
        workflow_state.has_medical_report = True
        workflow_state.profile_completed = False
        workflow_state.health_risk_level = "unknown"
        workflow_state.medical_report = parsed_report
        workflow_state.health_risk = None
        workflow_state.nutrition_analysis = None
        workflow_state.recipe_plan = []
        workflow_state.recommendations = []
        workflow_state.disease = []
        workflow_state.latest_profile_reply = ""
        workflow_state.latest_health_risk_reply = ""
        return {
            "workflow_state": workflow_state,
            "parsed_report": parsed_report,
            "report_missing_file": False,
        }

    def guard_node(state):
        workflow_state = state["workflow_state"]
        allowed, guard_message = master_agent.guard_agent.check(workflow_state, state["intent"])
        return {
            "workflow_state": workflow_state,
            "blocked": not allowed,
            "guard_message": guard_message or workflow_state.latest_guard_message,
        }

    def profile_node(state):
        workflow_state = state["workflow_state"]
        master_agent.user_profile_agent.build_profile(
            workflow_state,
            state["user_message"],
            generate_reply=state["intent"] == "profile_analysis",
        )
        return {"workflow_state": workflow_state}

    def nutrition_node(state):
        workflow_state = state["workflow_state"]
        nutrition = master_agent.nutrition_analysis_agent.analyze(workflow_state)
        return {
            "workflow_state": workflow_state,
            "nutrition": nutrition,
        }

    def recipe_node(state):
        workflow_state = state["workflow_state"]
        recipe_result = master_agent.recipe_generation_agent.generate(workflow_state, state["user_message"])
        if isinstance(recipe_result, str):
            return {
                "workflow_state": workflow_state,
                "recipes": list(workflow_state.recipe_plan),
                "recipe_reply": recipe_result,
            }
        recipes = recipe_result
        return {
            "workflow_state": workflow_state,
            "recipes": recipes,
            "recipe_reply": workflow_state.latest_recipe_reply,
        }

    def recommendation_node(state):
        workflow_state = state["workflow_state"]
        recommendations = master_agent.recommendation_agent.optimize(workflow_state)
        return {
            "workflow_state": workflow_state,
            "recommendations": recommendations,
        }

    def meal_record_node(state):
        workflow_state = state["workflow_state"]
        meal_record = master_agent.meal_record_agent.maybe_record(
            workflow_state,
            state["user_message"],
            before_image_bytes=state.get("meal_before_image_bytes"),
            before_image_name=state.get("meal_before_image_name"),
            after_image_bytes=state.get("meal_after_image_bytes"),
            after_image_name=state.get("meal_after_image_name"),
            uploaded_image_count=state.get("uploaded_image_count", 0),
        )
        if isinstance(meal_record, str):
            return {
                "workflow_state": workflow_state,
                "meal_record": None,
                "meal_record_reply": meal_record,
            }
        return {
            "workflow_state": workflow_state,
            "meal_record": meal_record,
            "meal_record_reply": "",
        }

    def diet_history_node(state):
        workflow_state = state["workflow_state"]
        diet_history_reply = master_agent.diet_history_analysis_agent.answer(
            session_id=state.get("session_id", ""),
            user_message=state["user_message"],
        )
        return {
            "workflow_state": workflow_state,
            "diet_history_reply": diet_history_reply,
        }

    def blocked_finalize_node(state):
        return {
            "intent": state["intent"],
            "fallback_reply": state["guard_message"],
        }

    def finalize_node(state):
        workflow_state = state["workflow_state"]
        intent = state["intent"]
        parsed_report = state.get("parsed_report")
        risk = state.get("risk") or workflow_state.health_risk or HealthRiskData(level=workflow_state.health_risk_level)
        nutrition = state.get("nutrition") or workflow_state.nutrition_analysis or NutritionAnalysisData()
        recipes = state.get("recipes") or workflow_state.recipe_plan
        recipe_reply = state.get("recipe_reply") or workflow_state.latest_recipe_reply
        recommendations = state.get("recommendations") or workflow_state.recommendations
        meal_record = state.get("meal_record")
        meal_record_reply = state.get("meal_record_reply") or ""
        diet_history_reply = state.get("diet_history_reply") or ""
        health_risk_reply = state.get("health_risk_reply") or workflow_state.latest_health_risk_reply
        if intent == "report_parsing" and state.get("report_missing_file"):
            fallback_reply = "当前暂不启用文件解析主流程。请直接说明你的饮食目标、忌口、过敏信息或食堂用餐需求。"
        elif intent == "meal_record" and meal_record_reply:
            fallback_reply = meal_record_reply
        elif intent == "diet_history_analysis" and diet_history_reply:
            fallback_reply = diet_history_reply
        elif intent == "recipe_generation" and recipe_reply:
            fallback_reply = recipe_reply
        else:
            fallback_reply = master_agent._build_fallback_reply(
                intent=intent,
                workflow_state=workflow_state,
                risk=risk,
                nutrition=nutrition,
                recipes=recipes,
                recommendations=recommendations,
                meal_record=meal_record,
            )

        return {
            "intent": intent,
            "risk": risk,
            "nutrition": nutrition,
            "recipes": recipes,
            "recipe_reply": recipe_reply,
            "recommendations": recommendations,
            "parsed_report": parsed_report,
            "meal_record": meal_record,
            "meal_record_reply": meal_record_reply,
            "diet_history_reply": diet_history_reply,
            "health_risk_reply": health_risk_reply,
            "fallback_reply": fallback_reply,
        }

    def route_after_guard(state):
        if state.get("blocked"):
            return "blocked"
        if state["intent"] == "meal_record":
            return "meal_record"
        if state["intent"] == "diet_history_analysis":
            return "diet_history"
        return "profile"

    def route_after_profile(state):
        if state["intent"] == "profile_analysis":
            return "finalize"
        if state["intent"] == "recommendation":
            return "recommendation"
        return "nutrition"

    def route_after_nutrition(state):
        return "recipe"

    graph_builder = StateGraph(cast(Any, GraphState))
    graph_builder.add_node("infer_intent_node", infer_intent_node)
    graph_builder.add_node("guard_node", guard_node)
    graph_builder.add_node("profile_node", profile_node)
    graph_builder.add_node("nutrition_node", nutrition_node)
    graph_builder.add_node("recipe_node", recipe_node)
    graph_builder.add_node("recommendation_node", recommendation_node)
    graph_builder.add_node("meal_record_node", meal_record_node)
    graph_builder.add_node("diet_history_node", diet_history_node)
    graph_builder.add_node("blocked_finalize_node", blocked_finalize_node)
    graph_builder.add_node("finalize_node", finalize_node)

    graph_builder.set_entry_point("infer_intent_node")
    graph_builder.add_edge("infer_intent_node", "guard_node")
    graph_builder.add_conditional_edges(
        "guard_node",
        cast(Any, route_after_guard),
        {
            "blocked": "blocked_finalize_node",
            "profile": "profile_node",
            "meal_record": "meal_record_node",
            "diet_history": "diet_history_node",
        },
    )
    graph_builder.add_conditional_edges(
        "profile_node",
        cast(Any, route_after_profile),
        {
            "finalize": "finalize_node",
            "recommendation": "recommendation_node",
            "nutrition": "nutrition_node",
        },
    )
    graph_builder.add_conditional_edges(
        "nutrition_node",
        cast(Any, route_after_nutrition),
        {
            "finalize": "finalize_node",
            "recipe": "recipe_node",
        },
    )
    graph_builder.add_edge("recipe_node", "finalize_node")
    graph_builder.add_edge("recommendation_node", "finalize_node")
    graph_builder.add_edge("meal_record_node", "finalize_node")
    graph_builder.add_edge("diet_history_node", "finalize_node")
    graph_builder.add_edge("blocked_finalize_node", END)
    graph_builder.add_edge("finalize_node", END)

    return graph_builder.compile()
