"""
检索增强生成（RAG）
------------------
核心流程：
    1. 用 ArchiveRetriever 检索与问题最相关的档案片段
    2. 把检索到的片段作为"档案资料"拼进 prompt
    3. 让 LLM 以村寨代言人的身份，结合对话历史生成自然回答

这样既保留了 LLM 的语言能力，又用真实档案锚定了历史事实，避免幻觉。
"""
import json
from urllib.parse import quote

from openai import OpenAI

from . import config
from .knowledge import VILLAGE_COORDS, VILLAGE_EXPERIENCE, VILLAGE_LODGING
from .memory_store import UserMemoryStore
from .personas import build_system_prompt
from .orchestrator import OrchestratorAgent
from .retriever import ArchiveRetriever
from .verifier import FactCheckerAgent

# 最多向模型回传多少轮历史消息
HISTORY_LIMIT = 8

# 这些属于寒暄/闲聊，不强制附加档案来源
CHITCHAT_KEYWORDS = {
    "你好", "您好", "在吗", "你是谁", "你能做什么", "谢谢", "再见",
    "介绍你自己", "介绍自己", "早上好", "下午好", "晚上好",
}

LOCAL_GUIDE_ATTRACTION_HINTS = ("景点", "好玩", "游玩", "参观", "纪念馆", "旧址", "古镇", "哪里玩", "有什么玩")
LOCAL_GUIDE_FOOD_HINTS = ("美食", "好吃", "小吃", "特产", "餐厅", "吃")
LOCAL_GUIDE_LODGING_HINTS = ("住宿", "酒店", "民宿", "住哪", "住哪里", "过夜")


class VillageAgent:
    """村寨数字代言人 Agent：检索 + 多轮记忆 + 生成"""

    def __init__(self, api_key: str = None):
        """
        初始化 Agent。

        参数:
            api_key: DeepSeek API key，默认从 config 读取
        """
        # 初始化 LLM 客户端（DeepSeek 兼容 OpenAI 接口）
        self.client = OpenAI(
            api_key=api_key or config.DEEPSEEK_API_KEY,
            base_url=config.BASE_URL,
        )

        # 初始化检索器
        self.retriever = ArchiveRetriever()

        # 当前对话的村寨（用于切换人格）
        self.current_village = None
        self.current_user = None
        self.current_persona_mode = "tourist"
        self.current_profile = None

        # 未登录游客的临时对话记忆；登录用户改由 UserMemoryStore 持久化
        self.conversation_history = {}
        self.memory_store = UserMemoryStore()

        # ??????????????????
        self.orchestrator = None
        self.last_plan = None
        self.last_tool_results = None
        self.last_evidence = None
        self.fact_checker = None
        self.last_verification = None

    def ask(self, question: str, village: str = None, user_id: str = None, persona_mode: str = None) -> str:
        """
        用户提问，返回村寨代言人的回答。

        参数:
            question:     用户的问题
            village:      可选，指定村寨
            user_id:      登录用户名；为空时使用游客临时记忆
            persona_mode: student / tourist / researcher
        """
        if village:
            self.current_village = village
            if self.current_user is None and user_id is None:
                self.conversation_history.setdefault(village, [])

        self.current_user = user_id
        if self.current_user:
            self.current_profile = self.memory_store.get_profile(self.current_user)
            self.current_persona_mode = persona_mode or self.current_profile.get("persona_mode") or "tourist"
            history = self.memory_store.get_history(self.current_user, self.current_village)
        else:
            self.current_profile = None
            self.current_persona_mode = persona_mode or "tourist"
            history = self.conversation_history.get(self.current_village, [])

        # 0. 如果问题像复杂任务，先尝试 Planner + 工具调用
        orchestrator_result = self._run_orchestrator(question, history)
        if orchestrator_result and orchestrator_result.get("handled"):
            answer = orchestrator_result["answer"]
            answer = self._attach_local_guide(question, self.current_village, answer)
            self.last_plan = orchestrator_result.get("plan")
            self.last_tool_results = orchestrator_result.get("tool_results")
            self.last_evidence = self._extract_evidence(orchestrator_result.get("tool_results"))
            self.last_verification = orchestrator_result.get("verification")
            self._remember(question, answer, history)
            return answer

        self.last_plan = None
        self.last_tool_results = None
        self.last_evidence = None
        self.last_verification = None

        # 1. 检索相关档案片段
        # 检索时把最近几轮对话一起带上，方便处理“后来呢”“他呢”这类追问
        recent_context = [turn["content"] for turn in history[-6:]]
        retrieval_query = question
        if recent_context:
            retrieval_query = question + "\n" + "\n".join(recent_context)

        results = self.retriever.search(retrieval_query, village=self.current_village)
        self.last_evidence = results

        # 2. 组装档案资料
        archive_text = self._format_archive(results)

        # 3. 组装 system prompt（村寨人格 + 讲解模式 + 用户画像）
        system_prompt = build_system_prompt(
            self.current_village,
            persona_mode=self.current_persona_mode,
            user_profile=self.current_profile,
        )

        # 4. 组装 user prompt（问题 + 档案资料）
        user_prompt = self._build_user_prompt(question, archive_text)

        # 5. 组装完整消息：system + 历史对话 + 当前问题
        messages = [{"role": "system", "content": system_prompt}]
        for turn in history[-HISTORY_LIMIT:]:
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": user_prompt})

        # 6. 调用 LLM 生成回答
        response = self.client.chat.completions.create(
            model=config.MODEL_NAME,
            messages=messages,
            temperature=config.TEMPERATURE,
            max_tokens=config.MAX_TOKENS,
        )

        answer = (response.choices[0].message.content or "").strip()

        # 7. 来源统一由前端“证据链”卡片展示，回答正文不再追加来源

        # 7.5 普通 RAG 也走反幻觉校验，补齐证据链
        verification = self._run_fact_checker(question, answer, archive_text)
        if verification.get("revised_answer"):
            answer = verification["revised_answer"]
        self.last_verification = verification
        answer = self._attach_local_guide(question, self.current_village, answer)
        self.last_plan = {
            "is_complex": False,
            "task_type": "archive_qa",
            "reasoning": "简单档案问答，使用 RAG 检索档案证据。",
            "steps": [],
        }

        # 8. 保存本轮对话记忆：登录用户写入数据库，游客写入页面内存
        self._remember(question, answer, history)

        return answer

    @staticmethod
    def _extract_evidence(tool_results):
        """从工具结果中提取 search_archives 返回的档案证据。"""
        evidence = []
        for item in tool_results or []:
            if item.get("tool") != "search_archives":
                continue
            try:
                data = json.loads(item.get("result") or "[]")
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            for row in data[:5]:
                if isinstance(row, dict):
                    evidence.append({
                        "text": (row.get("text") or "")[:1000],
                        "source": row.get("source") or "未知档案",
                        "score": row.get("score"),
                    })
        return evidence

    @staticmethod
    def _platform_search_url(keyword: str, platform: str = "xiaohongshu") -> str:
        if platform == "douyin":
            return "https://www.douyin.com/search/" + quote(keyword)
        return (
            "https://www.xiaohongshu.com/search_result?keyword="
            + quote(keyword)
            + "&source=web_search_result_notes"
        )

    def _resolve_guide_village(self, question, village=None):
        q = question or ""
        for name in VILLAGE_COORDS:
            if name and name in q:
                return name
        return village or self.current_village

    def _local_guide_block(self, question, village=None):
        q = question or ""
        target = self._resolve_guide_village(q, village)
        if not target:
            return ""

        exp = VILLAGE_EXPERIENCE.get(target, {})
        lodging = VILLAGE_LODGING.get(target, "")

        want_attraction = any(hint in q for hint in LOCAL_GUIDE_ATTRACTION_HINTS)
        want_food = any(hint in q for hint in LOCAL_GUIDE_FOOD_HINTS)
        want_lodging = any(hint in q for hint in LOCAL_GUIDE_LODGING_HINTS)
        if not (want_attraction or want_food or want_lodging):
            return ""

        lines = ["", "📍 本地攻略直达："]

        if want_attraction:
            for name in exp.get("attractions", [])[:3]:
                xhs = self._platform_search_url(f"{target} {name} 景点", "xiaohongshu")
                dy = self._platform_search_url(f"{target} {name}", "douyin")
                lines.append(f"- {name}：[小红书]({xhs}) · [抖音]({dy})")

        if want_food:
            for name in exp.get("food", [])[:3]:
                xhs = self._platform_search_url(f"{target} {name} 美食", "xiaohongshu")
                dy = self._platform_search_url(f"{target} {name}", "douyin")
                lines.append(f"- {name}：[小红书]({xhs}) · [抖音]({dy})")

        if want_lodging and lodging:
            xhs = self._platform_search_url(f"{target} 住宿 {lodging}", "xiaohongshu")
            dy = self._platform_search_url(f"{target} 住宿", "douyin")
            lines.append(f"- 住宿参考：[小红书]({xhs}) · [抖音]({dy})")

        if len(lines) == 2:
            return ""
        return "\n".join(lines)

    def _attach_local_guide(self, question, village, answer):
        block = self._local_guide_block(question, village)
        if not block or not answer:
            return answer
        return answer.rstrip() + "\n" + block

    def _run_fact_checker(self, question: str, answer: str, evidence_text: str):
        """?????? Agent ????????????"""
        if self.fact_checker is None:
            self.fact_checker = FactCheckerAgent()
        return self.fact_checker.verify(question, answer, evidence_text)

    def _run_orchestrator(self, question: str, history: list):
        """??? Planner + ???????????"""
        if self.orchestrator is None:
            self.orchestrator = OrchestratorAgent(retriever=self.retriever)
        return self.orchestrator.run(
            question=question,
            village=self.current_village,
            history=history,
        )

    def _remember(self, question: str, answer: str, history: list) -> None:
        """保存本轮对话：登录用户写入持久化记忆，游客写入内存。"""
        if self.current_user:
            self.memory_store.append_turn(self.current_user, self.current_village, "user", question)
            self.memory_store.append_turn(self.current_user, self.current_village, "assistant", answer)
            self.memory_store.update_profile(
                self.current_user,
                persona_mode=self.current_persona_mode,
                village=self.current_village,
                question=question,
            )
            return

        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": answer})
        if len(history) > HISTORY_LIMIT * 2:
            history = history[-HISTORY_LIMIT * 2:]
        self.conversation_history[self.current_village] = history

    @staticmethod
    def _format_archive(results: list) -> str:
        """把检索到的档案片段格式化成 LLM 可读的文本"""
        if not results:
            return (
                "（本次未检索到相关档案资料。"
                "如果用户问的是寒暄、路线咨询或常识，请自然回应；"
                "如果用户问的是具体历史事实，请说明档案里没记清，不要编造数字、人名或日期。）"
            )

        blocks = []
        for i, r in enumerate(results, 1):
            blocks.append("【档案" + str(i) + "】（来源：" + r["source"] + "）\n" + r["text"])

        return "\n\n".join(blocks)

    @staticmethod
    def _build_user_prompt(question: str, archive_text: str) -> str:
        """组装发送给 LLM 的 user prompt"""
        return (
            "【用户当前问题】\n" + question + "\n\n"
            "【可参考的档案资料】\n" + archive_text + "\n\n"
            "请结合对话历史和当前问题，以村寨代言人的身份自然回应。\n"
            "回答要求：\n"
            "1. 如果是具体历史事实，数字、人名、日期、部队番号必须严格照抄档案，不得编造。\n"
            "2. 如果是寒暄、追问、普通聊天或路线咨询，直接自然回应，不要硬套档案，也不要重复固定格式。\n"
            "3. 不要在回答末尾追加“——据《...》”或罗列档案来源；来源会由证据链单独展示。"
        )

    @staticmethod
    def _maybe_add_source(answer: str, results: list, question: str) -> str:
        """只在确需溯源时自然补充来源，避免每轮都机械地加“档案来源”。"""
        if not results:
            return answer

        # 闲聊问题不强加来源
        if any(word in question for word in CHITCHAT_KEYWORDS):
            return answer

        # 模型已经自然带出来源时，不再重复添加
        if "《" in answer or "来源" in answer or "档案" in answer:
            return answer

        sources = []
        for r in results[:2]:
            source = r.get("source", "").strip()
            if source and source != "未知档案" and source not in sources:
                sources.append(source)

        if not sources:
            return answer

        return answer + "\n——据《" + "》《".join(sources) + "》"
