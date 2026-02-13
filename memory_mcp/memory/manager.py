"""
记忆管理器
实现情景+实体记忆模式，支持项目级和用户级存储
"""

import os
import re
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Any, Tuple
from uuid import uuid4
from ..vector import VectorStore, is_encoder_ready


class MemoryManager:
    """
    情景+实体记忆管理器

    - 用户级: 存储 Preference, Concept, Habit
    - 项目级: 存储 Decision, Episode, File, Architecture
    """

    # 实体类型分类
    USER_LEVEL_TYPES = {"Preference", "Concept", "Habit"}
    PROJECT_LEVEL_TYPES = {"Decision", "Episode", "File", "Architecture"}

    # 实体检测规则（模式 + 关键词 + 置信度）
    DETECTION_RULES = {
        "Decision": {
            "patterns": [
                r"(?:我|我们)?(?:决定|确定|选择|采用|使用)(?:了)?(.{5,50}?)(?:方案|方式|方法|来|作为|进行)?",
                r"(?:最终|最后)?(?:选择|采用|决定)(?:了)?(.{5,50})",
                r"(.{5,30}?)(?:是|作为)(?:最佳|最好|更好的)?(?:选择|方案)",
            ],
            "keywords": ["决定", "采用", "选择", "确定使用", "决策", "敲定"],
            "min_confidence": 0.7,
        },
        "Architecture": {
            "patterns": [
                r"(?:采用|使用|基于)(.{5,50}?)(?:架构|设计|模式|结构)",
                r"(?:架构|设计|结构)(?:是|为|采用)(.{5,50})",
                r"(.{5,30}?)(?:分层|模块化|微服务|单体)",
            ],
            "keywords": ["架构", "设计模式", "分层", "模块", "组件结构"],
            "min_confidence": 0.7,
        },
        "Preference": {
            "patterns": [
                r"(?:我|用户)?(?:喜欢|偏好|倾向于|更愿意)(.{5,50})",
                r"(?:prefer|偏好)(?:使用|用)?(.{5,50})",
            ],
            "keywords": ["喜欢", "偏好", "倾向于", "prefer", "更喜欢"],
            "min_confidence": 0.6,
        },
        "Concept": {
            "patterns": [
                r"(.{2,20}?)(?:是指|是什么|的意思是|定义为)(.{10,100})",
                r"(?:什么是|解释一下)(.{2,20})",
                r"我是(.{2,20}?)(?:，|,|。|$)",  # 用户身份：我是XXX
                r"我叫(.{2,10})",  # 用户身份：我叫XXX
                r"我的名字是(.{2,10})",  # 用户身份：我的名字是XXX
                r"(?:我|用户)是(.{2,30}?)(?:的|，|,|。|$)",  # 用户角色/身份
            ],
            "keywords": ["是什么", "什么是", "意思是", "定义", "概念", "解释", "我是", "我叫"],
            "min_confidence": 0.5,
        },
        "Habit": {
            "patterns": [
                r"(?:我|用户)?(?:习惯|总是|一般会|通常|每次都)(.{5,50})",
            ],
            "keywords": ["习惯", "总是", "一般会", "通常", "每次都"],
            "min_confidence": 0.6,
        },
        "File": {
            "patterns": [
                r"(.{5,50}\.(?:ts|js|vue|py|java|go))(?:文件)?(?:负责|处理|实现|包含)(.{5,50})",
                r"(?:在|修改|创建|查看)(.{5,50}\.(?:ts|js|vue|py|java|go))",
            ],
            "keywords": [".ts", ".js", ".vue", ".py", "文件负责", "文件处理"],
            "min_confidence": 0.8,
        },
    }

    # 自动确认的置信度阈值
    AUTO_CONFIRM_THRESHOLD = 0.85

    # 情景过期时间（分钟），超过此时间未活动的情景会被自动关闭
    STALE_EPISODE_MINUTES = 30

    def __init__(
        self,
        project_path: Optional[str] = None,
        user_path: Optional[str] = None
    ):
        # 用户级路径（全局）
        self.user_path = Path(user_path or self._get_default_user_path())
        self.user_path.mkdir(parents=True, exist_ok=True)

        # 项目级路径
        self.project_path = Path(project_path or os.getcwd()) / ".claude" / "memory"
        self.project_path.mkdir(parents=True, exist_ok=True)

        # 初始化向量存储
        self.user_store = VectorStore(
            str(self.user_path / "user_db"),
            collection_name="user_memory"
        )
        self.project_store = VectorStore(
            str(self.project_path / "project_db"),
            collection_name="project_memory"
        )

        # 消息缓存文件
        self.cache_file = self.project_path / "message_cache.jsonl"

        # 待确认实体文件
        self.pending_file = self.project_path / "pending_entities.json"

        # 当前活跃情景
        self.current_episode: Optional[Dict] = None
        self.current_messages: List[Dict] = []

        # 待确认的实体候选
        self.pending_entities: List[Dict] = []

        # 加载状态
        self._load_active_episode()
        self._load_pending_entities()

        # 检测并关闭过期情景
        self._close_stale_episode()

    def _get_default_user_path(self) -> str:
        """获取默认用户目录"""
        if os.name == 'nt':  # Windows
            return os.path.join(os.environ.get('APPDATA', ''), 'claude-memory')
        else:  # Mac/Linux
            return os.path.expanduser('~/.claude-memory')

    def _load_active_episode(self):
        """加载未完成的情景"""
        state_file = self.project_path / "active_episode.json"
        if state_file.exists():
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.current_episode = data.get("episode")
                    self.current_messages = data.get("messages", [])
            except (json.JSONDecodeError, IOError):
                pass

    def _load_pending_entities(self):
        """加载待确认的实体"""
        if self.pending_file.exists():
            try:
                with open(self.pending_file, 'r', encoding='utf-8') as f:
                    self.pending_entities = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.pending_entities = []

    def _close_stale_episode(self):
        """检测并关闭过期情景（上次活动超过 STALE_EPISODE_MINUTES 分钟）"""
        if not self.current_episode:
            return

        # 获取最后活动时间
        last_activity = None

        # 优先使用最后一条消息的时间
        if self.current_messages:
            last_msg = self.current_messages[-1]
            last_activity = datetime.fromisoformat(last_msg["timestamp"])
        else:
            # 否则使用情景创建时间
            last_activity = datetime.fromisoformat(self.current_episode["created_at"])

        # 计算过期时间
        now = datetime.now()
        stale_minutes = (now - last_activity).total_seconds() / 60

        if stale_minutes >= self.STALE_EPISODE_MINUTES:
            # 情景过期，自动关闭
            episode_title = self.current_episode.get("title", "未命名情景")
            auto_summary = f"[自动关闭] {episode_title} (闲置 {int(stale_minutes)} 分钟后自动归档)"

            # 日志记录
            import sys
            print(
                f"[memory-mcp] Auto-closing stale episode: {episode_title} "
                f"(idle for {int(stale_minutes)} minutes)",
                file=sys.stderr
            )

            self.close_episode(summary=auto_summary)

    def _save_pending_entities(self):
        """保存待确认的实体"""
        with open(self.pending_file, 'w', encoding='utf-8') as f:
            json.dump(self.pending_entities, f, ensure_ascii=False, indent=2)

    def _save_active_episode(self):
        """保存当前情景状态"""
        state_file = self.project_path / "active_episode.json"
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump({
                "episode": self.current_episode,
                "messages": self.current_messages
            }, f, ensure_ascii=False, indent=2)

    # ==================== 消息处理 ====================

    def _clean_content(self, content: str, max_length: int = 2000) -> str:
        """清理消息内容：去除代码块，截断长度"""
        # 去除代码块（保留代码块的说明）
        cleaned = re.sub(
            r'```[\w]*\n[\s\S]*?```',
            '[代码块已省略]',
            content
        )

        # 去除行内代码
        cleaned = re.sub(r'`[^`]+`', '[代码]', cleaned)

        # 截断长度
        if len(cleaned) > max_length:
            cleaned = cleaned[:max_length] + "...[已截断]"

        return cleaned.strip()

    def _extract_text_summary(self, content: str) -> str:
        """提取消息的文本摘要（用于向量存储）"""
        # 去除代码块
        text = re.sub(r'```[\w]*\n[\s\S]*?```', '', content)
        # 去除行内代码
        text = re.sub(r'`[^`]+`', '', text)
        # 去除多余空行
        text = re.sub(r'\n{3,}', '\n\n', text)
        # 截断
        if len(text) > 500:
            text = text[:500] + "..."
        return text.strip()

    # ==================== 消息缓存 ====================

    def cache_message(self, role: str, content: str) -> Dict:
        """缓存消息（实时存储，防丢失）"""
        # 清理内容，避免存储过大
        cleaned_content = self._clean_content(content)

        message = {
            "id": f"msg_{uuid4().hex[:8]}",
            "role": role,
            "content": cleaned_content,
            "timestamp": datetime.now().isoformat(),
            "episode_id": self.current_episode["id"] if self.current_episode else None
        }

        # 追加到缓存文件
        with open(self.cache_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(message, ensure_ascii=False) + '\n')

        # 添加到当前情景
        self.current_messages.append(message)

        # 只对用户消息检测实体（用户的决策/偏好，不是 Claude 的建议）
        if role == "user":
            self._detect_and_process_entities(content)

        # 保存状态
        self._save_active_episode()

        return message

    def _detect_and_process_entities(self, content: str):
        """检测实体并处理（自动确认高置信度的）"""
        candidates = self._detect_candidates(content)

        for candidate in candidates:
            if candidate["confidence"] >= self.AUTO_CONFIRM_THRESHOLD:
                # 高置信度，自动确认
                self.add_entity(
                    entity_type=candidate["type"],
                    content=candidate["extracted_content"],
                    reason=f"自动确认 (置信度: {candidate['confidence']:.2f})"
                )
            else:
                # 低置信度，加入待确认列表
                self.pending_entities.append(candidate)

        # 保存待确认列表
        self._save_pending_entities()

    def _detect_candidates(self, content: str) -> List[Dict]:
        """检测可能的实体候选"""
        candidates = []
        detected_contents = set()  # 避免重复

        for entity_type, rules in self.DETECTION_RULES.items():
            # 先用正则模式匹配，提取关键内容
            for pattern in rules.get("patterns", []):
                try:
                    matches = re.findall(pattern, content, re.IGNORECASE)
                    for match in matches:
                        # match 可能是 tuple（多个捕获组）或 str
                        if isinstance(match, tuple):
                            extracted = " ".join(m for m in match if m).strip()
                        else:
                            extracted = match.strip()

                        if extracted and len(extracted) > 3 and extracted not in detected_contents:
                            detected_contents.add(extracted)
                            candidates.append({
                                "id": f"cand_{uuid4().hex[:8]}",
                                "type": entity_type,
                                "extracted_content": extracted[:200],  # 限制长度
                                "source_snippet": content[:300],  # 原文片段
                                "confidence": rules.get("min_confidence", 0.5) + 0.2,  # 模式匹配加分
                                "status": "pending",
                                "detected_at": datetime.now().isoformat(),
                                "detection_method": "pattern"
                            })
                except re.error:
                    continue

            # 再用关键词匹配（置信度较低）
            keywords = rules.get("keywords", [])
            if any(kw in content for kw in keywords):
                # 检查是否已有更高置信度的候选
                existing_types = {c["type"] for c in candidates}
                if entity_type not in existing_types:
                    # 提取包含关键词的句子
                    sentences = re.split(r'[。！？\n]', content)
                    for sentence in sentences:
                        if any(kw in sentence for kw in keywords) and len(sentence) > 5:
                            if sentence not in detected_contents:
                                detected_contents.add(sentence)
                                candidates.append({
                                    "id": f"cand_{uuid4().hex[:8]}",
                                    "type": entity_type,
                                    "extracted_content": sentence[:200],
                                    "source_snippet": content[:300],
                                    "confidence": rules.get("min_confidence", 0.5),
                                    "status": "pending",
                                    "detected_at": datetime.now().isoformat(),
                                    "detection_method": "keyword"
                                })
                            break  # 每种类型只取一个关键词匹配

        return candidates

    # ==================== 情景管理 ====================

    def start_episode(self, title: str, tags: List[str] = None) -> Dict:
        """开始新情景"""
        # 如果有未关闭的情景，先关闭
        if self.current_episode:
            self.close_episode()

        self.current_episode = {
            "id": f"ep_{uuid4().hex[:8]}",
            "title": title,
            "tags": tags or [],
            "status": "active",
            "created_at": datetime.now().isoformat(),
            "entity_ids": []
        }
        self.current_messages = []

        self._save_active_episode()

        return self.current_episode

    def close_episode(self, summary: Optional[str] = None) -> Optional[Dict]:
        """关闭当前情景"""
        if not self.current_episode:
            return None

        # 生成摘要
        if not summary:
            summary = self._generate_summary()

        # 准备元数据
        metadata = {
            "title": self.current_episode["title"],
            "tags": ",".join(self.current_episode["tags"]),
            "status": "completed",
            "entity_ids": ",".join(self.current_episode["entity_ids"]),
            "type": "Episode",
            "message_count": len(self.current_messages),
            "created_at": self.current_episode["created_at"],
            "closed_at": datetime.now().isoformat()
        }

        # 存入向量数据库
        self.project_store.add(
            doc_id=self.current_episode["id"],
            content=summary,
            metadata=metadata
        )

        closed_episode = self.current_episode.copy()
        closed_episode["summary"] = summary

        # 清空当前状态
        self.current_episode = None
        self.current_messages = []
        self._save_active_episode()

        return closed_episode

    def _generate_summary(self) -> str:
        """生成情景摘要"""
        if not self.current_messages:
            return self.current_episode.get("title", "空情景")

        # 简单摘要：取最近几条消息
        recent = self.current_messages[-5:]
        summary_parts = [f"{self.current_episode['title']}:"]

        for msg in recent:
            role = "用户" if msg["role"] == "user" else "助手"
            content = msg["content"][:100]
            summary_parts.append(f"- {role}: {content}")

        return "\n".join(summary_parts)

    def get_current_episode(self) -> Optional[Dict]:
        """获取当前情景（每次从磁盘重新加载，以便感知外部 hook 的修改）"""
        self._load_active_episode()
        return self.current_episode

    # ==================== 实体管理 ====================

    def add_entity(
        self,
        entity_type: str,
        content: str,
        reason: Optional[str] = None,
        related_ids: List[str] = None
    ) -> Dict:
        """添加实体"""
        entity_id = f"ent_{uuid4().hex[:8]}"

        metadata = {
            "type": entity_type,
            "status": "active",
            "reason": reason or "",
            "related_ids": ",".join(related_ids or []),
            "episode_id": self.current_episode["id"] if self.current_episode else "",
            "created_at": datetime.now().isoformat()
        }

        # 根据类型选择存储位置
        if entity_type in self.USER_LEVEL_TYPES:
            self.user_store.add(entity_id, content, metadata)
        else:
            self.project_store.add(entity_id, content, metadata)

        # 关联到当前情景
        if self.current_episode:
            self.current_episode["entity_ids"].append(entity_id)
            self._save_active_episode()

        return {
            "id": entity_id,
            "type": entity_type,
            "content": content,
            "metadata": metadata
        }

    def confirm_entity(self, candidate_id: str, entity_type: str, content: str) -> Dict:
        """确认候选实体"""
        # 移除候选
        self.pending_entities = [
            p for p in self.pending_entities if p["id"] != candidate_id
        ]
        self._save_pending_entities()

        # 添加正式实体
        return self.add_entity(entity_type, content)

    def reject_candidate(self, candidate_id: str):
        """拒绝候选实体"""
        self.pending_entities = [
            p for p in self.pending_entities if p["id"] != candidate_id
        ]
        self._save_pending_entities()

    def clear_old_pending(self, days: int = 7):
        """清理超过指定天数的待确认实体"""
        cutoff = datetime.now().timestamp() - (days * 24 * 3600)
        self.pending_entities = [
            p for p in self.pending_entities
            if datetime.fromisoformat(p["detected_at"]).timestamp() > cutoff
        ]
        self._save_pending_entities()

    def deprecate_entity(self, entity_id: str, superseded_by: Optional[str] = None):
        """废弃实体"""
        # 尝试在两个存储中查找
        entity = self.project_store.get(entity_id)
        store = self.project_store

        if not entity:
            entity = self.user_store.get(entity_id)
            store = self.user_store

        if entity:
            metadata = entity["metadata"]
            metadata["status"] = "deprecated"
            metadata["deprecated_at"] = datetime.now().isoformat()
            if superseded_by:
                metadata["superseded_by"] = superseded_by

            store.update(entity_id, metadata=metadata)

    def get_pending_entities(self) -> List[Dict]:
        """获取待确认的实体"""
        return self.pending_entities

    # ==================== 检索 ====================

    def recall(
        self,
        query: str,
        top_k: int = 5,
        include_deprecated: bool = False
    ) -> Dict:
        """综合检索"""
        # 记录搜索模式（向量搜索 or 关键词降级）
        using_vector_search = is_encoder_ready()

        # 实体过滤条件：active 或包含 deprecated
        entity_filter = None if include_deprecated else {"status": "active"}

        # Episode 过滤条件：completed（已归档的情景）
        episode_filter = {"$and": [{"type": "Episode"}, {"status": "completed"}]}

        # 检索项目级实体（排除 Episode）
        entity_filter_with_type = {"$and": [{"type": {"$ne": "Episode"}}, {"status": "active"}]} if not include_deprecated else {"type": {"$ne": "Episode"}}
        project_entities = self.project_store.search(
            query,
            top_k=top_k,
            where=entity_filter_with_type
        )

        # 单独检索 Episode（使用 completed 状态）
        episodes = self.project_store.search(
            query,
            top_k=top_k,
            where=episode_filter
        )

        # 检索用户级
        user_results = self.user_store.search(
            query,
            top_k=top_k,
            where=entity_filter
        )

        # 合并实体结果
        entities = project_entities + user_results

        result = {
            "episodes": episodes,
            "entities": entities,
            "current": {
                "episode": self.current_episode,
                "recent_messages": self.current_messages[-5:]
            }
        }

        # 如果使用了降级搜索，添加提示
        if not using_vector_search:
            result["_note"] = "向量编码器正在初始化中，当前使用关键词匹配（结果可能不够精确）"

        return result

    def search_by_type(
        self,
        entity_type: str,
        query: Optional[str] = None,
        top_k: int = 10
    ) -> List[Dict]:
        """
        按类型检索实体

        - 无 query：直接从数据库按类型过滤，不需要向量编码器
        - 有 query：使用向量语义搜索，需要编码器就绪
        """
        store = self.user_store if entity_type in self.USER_LEVEL_TYPES else self.project_store

        # Episode 使用 "completed" 状态（已归档），其他实体使用 "active" 状态
        status = "completed" if entity_type == "Episode" else "active"

        if query:
            # 有 query 时使用语义搜索，需要编码器
            results = store.search(
                query,
                top_k=top_k,
                where={"$and": [{"type": entity_type}, {"status": status}]}
            )
        else:
            # 无 query 时直接按类型过滤，不需要编码器
            results = store.get_by_type(entity_type, limit=top_k, status=status)

        return results

    def get_episode_detail(self, episode_id: str) -> Optional[Dict]:
        """获取情景详情（按 ID 查询，不需要向量编码器）"""
        # 按 ID 查询使用 ChromaDB 的 get() 方法，不需要向量编码器
        episode = self.project_store.get(episode_id)
        if not episode:
            return None

        # 获取关联的消息
        messages = []
        if self.cache_file.exists():
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                for line in f:
                    msg = json.loads(line)
                    if msg.get("episode_id") == episode_id:
                        messages.append(msg)

        # 获取关联的实体
        entity_ids = episode["metadata"].get("entity_ids", "").split(",")
        entities = []
        for eid in entity_ids:
            if eid:
                ent = self.project_store.get(eid) or self.user_store.get(eid)
                if ent:
                    entities.append(ent)

        return {
            **episode,
            "messages": messages,
            "entities": entities
        }

    # ==================== 日志管理 ====================

    def clear_message_cache(self) -> Dict:
        """清空消息缓存日志"""
        lines_before = 0
        if self.cache_file.exists():
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                lines_before = sum(1 for _ in f)
            # 清空文件
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                pass

        return {
            "status": "cleared",
            "lines_removed": lines_before,
            "file": str(self.cache_file)
        }

    def cleanup_old_messages(self, days: int = 7) -> Dict:
        """
        清理超过指定天数的消息缓存

        Args:
            days: 保留最近 N 天的消息，默认 7 天
        """
        if not self.cache_file.exists():
            return {"status": "no_cache_file", "removed": 0, "kept": 0}

        cutoff = datetime.now().timestamp() - (days * 24 * 3600)
        kept_messages = []
        removed_count = 0

        with open(self.cache_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    msg = json.loads(line)
                    msg_time = datetime.fromisoformat(msg["timestamp"]).timestamp()
                    if msg_time > cutoff:
                        kept_messages.append(line)
                    else:
                        removed_count += 1
                except (json.JSONDecodeError, KeyError):
                    # 保留无法解析的行（避免数据丢失）
                    kept_messages.append(line)

        # 重写文件
        with open(self.cache_file, 'w', encoding='utf-8') as f:
            f.writelines(kept_messages)

        return {
            "status": "cleaned",
            "days_kept": days,
            "removed": removed_count,
            "kept": len(kept_messages)
        }

    def list_all_episodes(
        self,
        order: str = "desc",
        limit: int = 100
    ) -> List[Dict]:
        """
        列出所有情景（按时间排序，不依赖语义搜索）

        Args:
            order: 排序方式，"desc"（最新在前）或 "asc"（最早在前）
            limit: 返回数量限制
        """
        # 直接从向量存储获取所有 Episode 类型的记录
        all_episodes = self.project_store.get_by_type(
            "Episode",
            limit=limit * 2,  # 多取一些以便排序后截取
            status="completed"
        )

        # 按创建时间排序
        def get_created_at(ep):
            created = ep.get("metadata", {}).get("created_at", "")
            try:
                return datetime.fromisoformat(created).timestamp()
            except (ValueError, TypeError):
                return 0

        sorted_episodes = sorted(
            all_episodes,
            key=get_created_at,
            reverse=(order == "desc")
        )

        return sorted_episodes[:limit]

    # ==================== 统计 ====================

    def get_stats(self) -> Dict:
        """获取记忆统计"""
        # 统计各类型实体数量
        pending_by_type = {}
        for p in self.pending_entities:
            t = p.get("type", "Unknown")
            pending_by_type[t] = pending_by_type.get(t, 0) + 1

        return {
            "project": {
                "path": str(self.project_path),
                "count": self.project_store.count()
            },
            "user": {
                "path": str(self.user_path),
                "count": self.user_store.count()
            },
            "current_episode": self.current_episode["title"] if self.current_episode else None,
            "current_messages": len(self.current_messages),
            "pending_entities": {
                "total": len(self.pending_entities),
                "by_type": pending_by_type
            },
            "auto_confirm_threshold": self.AUTO_CONFIRM_THRESHOLD,
            "encoder_ready": is_encoder_ready(),
            "_tip": "encoder_ready=false 时，语义搜索不可用，但按 ID/类型查询仍可工作"
        }
