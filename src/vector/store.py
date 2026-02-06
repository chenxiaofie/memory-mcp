"""
向量存储模块
使用 ChromaDB 作为向量数据库

优化策略：
1. 使用独立进程加载编码器，避免 GIL 阻塞主线程
2. 解决竞态条件：_init_process_pool() 同步等待预热完成，确保编码器真正就绪
   - 修复 workflow 框架中"向量编码器正在加载中"的误报问题
   - 确保 encode_text() 调用时编码器已完全就绪
3. 子进程监控父进程：防止父进程退出后子进程成为孤儿进程
"""

import chromadb
from chromadb.config import Settings
from typing import List, Dict, Optional, Any
from pathlib import Path
import json
import os
import sys
import logging
import threading
import time
from concurrent.futures import ProcessPoolExecutor, Future
import multiprocessing

logger = logging.getLogger(__name__)

# 模型配置
MODEL_NAME = 'paraphrase-multilingual-MiniLM-L12-v2'

# 全局状态
_encoder_ready = False
_encoder_loading = False
_encoder_lock = threading.Lock()

# 进程池（用于编码操作）
_process_pool: Optional[ProcessPoolExecutor] = None
_warmup_future: Optional[Future] = None  # 预热任务的 Future
_pool_lock = threading.Lock()

# 保存父进程 PID（用于传递给子进程）
_parent_pid: Optional[int] = None


def is_encoder_ready() -> bool:
    """检查编码器是否已加载完成"""
    return _encoder_ready


def is_encoder_loading() -> bool:
    """检查编码器是否正在加载中"""
    return _encoder_loading


# ==================== 子进程父进程监控 ====================

def _is_parent_alive(parent_pid: int) -> bool:
    """检查父进程是否存活（跨平台）"""
    try:
        if sys.platform == 'win32':
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            SYNCHRONIZE = 0x00100000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, parent_pid)
            if handle == 0:
                return False
            # 检查进程是否已退出
            WAIT_TIMEOUT = 258
            result = kernel32.WaitForSingleObject(handle, 0)
            kernel32.CloseHandle(handle)
            return result == WAIT_TIMEOUT  # WAIT_TIMEOUT 表示进程仍在运行
        else:
            # Unix: 发送信号 0 检查进程是否存在
            os.kill(parent_pid, 0)
            return True
    except (OSError, Exception):
        return False


def _worker_parent_monitor(parent_pid: int):
    """
    子进程中的父进程监控守护线程

    当父进程退出时，子进程也退出，防止成为孤儿进程
    """
    while True:
        time.sleep(3)  # 每 3 秒检查一次
        if not _is_parent_alive(parent_pid):
            # 父进程已退出，子进程也退出
            os._exit(0)


def _worker_initializer(parent_pid: int):
    """
    子进程初始化函数

    在子进程启动时调用，启动父进程监控守护线程
    """
    # 启动父进程监控守护线程
    monitor_thread = threading.Thread(
        target=_worker_parent_monitor,
        args=(parent_pid,),
        daemon=True,
        name="parent-monitor"
    )
    monitor_thread.start()


def _encode_in_process(text: str, model_name: str) -> List[float]:
    """
    在独立进程中执行编码（进程池 worker 函数）

    注意：这个函数在子进程中运行，每个子进程会加载自己的模型实例
    """
    # 使用进程级缓存避免重复加载
    if not hasattr(_encode_in_process, '_model'):
        from sentence_transformers import SentenceTransformer
        _encode_in_process._model = SentenceTransformer(model_name)

    return _encode_in_process._model.encode(text).tolist()


def _batch_encode_in_process(texts: List[str], model_name: str) -> List[List[float]]:
    """
    在独立进程中批量编码
    """
    if not hasattr(_batch_encode_in_process, '_model'):
        from sentence_transformers import SentenceTransformer
        _batch_encode_in_process._model = SentenceTransformer(model_name)

    return [vec.tolist() for vec in _batch_encode_in_process._model.encode(texts)]


def _init_process_pool():
    """初始化进程池（懒加载），确保编码器就绪后返回"""
    global _process_pool, _warmup_future, _encoder_loading, _encoder_ready, _parent_pid

    with _pool_lock:
        if _process_pool is not None:
            # 进程池已存在，检查预热任务是否完成
            if _warmup_future is not None and not _warmup_future.done():
                # 预热任务未完成，同步等待（解决竞态条件）
                logger.info("[memory-mcp] Waiting for encoder warmup to complete...")
                try:
                    _warmup_future.result(timeout=60.0)  # 最多等待 60 秒
                    _encoder_ready = True
                    _encoder_loading = False
                    logger.info("[memory-mcp] Encoder warmup completed")
                except Exception as e:
                    _encoder_loading = False
                    logger.error(f"[memory-mcp] Encoder warmup failed: {e}")
                    raise RuntimeError(f"编码器预热失败: {e}")
            return _process_pool

        _encoder_loading = True
        try:
            # 保存当前进程 PID，用于子进程监控
            _parent_pid = os.getpid()

            # 创建进程池，使用 spawn 方式避免继承主进程状态
            # max_workers=1 确保模型只加载一次
            # initializer 用于在子进程中启动父进程监控
            ctx = multiprocessing.get_context('spawn')
            _process_pool = ProcessPoolExecutor(
                max_workers=1,
                mp_context=ctx,
                initializer=_worker_initializer,
                initargs=(_parent_pid,)
            )

            # 提交一个预热任务，触发子进程中的模型加载
            # 这不会阻塞主进程（GIL 在子进程中）
            _warmup_future = _process_pool.submit(_encode_in_process, "warmup", MODEL_NAME)

            # 使用回调标记加载完成（用于异步场景）
            def on_done(f):
                global _encoder_ready, _encoder_loading
                try:
                    f.result()  # 检查是否有异常
                    _encoder_ready = True
                    logger.info("[memory-mcp] Encoder ready (subprocess)")
                except Exception as e:
                    logger.error(f"[memory-mcp] Encoder init failed: {e}")
                finally:
                    _encoder_loading = False

            _warmup_future.add_done_callback(on_done)

            return _process_pool
        except Exception as e:
            _encoder_loading = False
            logger.error(f"[memory-mcp] Failed to init process pool: {e}")
            raise


def get_process_pool() -> Optional[ProcessPoolExecutor]:
    """获取进程池（如果已初始化）"""
    return _process_pool


def encode_text(text: str, timeout: float = 60.0) -> List[float]:
    """
    编码文本（使用进程池）

    Args:
        text: 要编码的文本
        timeout: 超时时间（秒）

    Returns:
        向量列表

    Raises:
        RuntimeError: 如果编码器未就绪或超时
    """
    # 初始化进程池并等待预热完成（内部已处理竞态条件）
    pool = _init_process_pool()

    # 编码器已就绪，执行编码
    try:
        future = pool.submit(_encode_in_process, text, MODEL_NAME)
        return future.result(timeout=timeout)
    except Exception as e:
        raise RuntimeError(f"编码失败: {e}")


def start_encoder_warmup():
    """
    启动编码器预热（非阻塞）

    在独立进程中加载模型，不会阻塞主进程
    """
    # 初始化进程池会触发预热
    threading.Thread(target=_init_process_pool, daemon=True, name="encoder-warmup").start()


def shutdown_encoder():
    """
    关闭编码器进程池，释放资源

    必须在程序退出前调用，否则子进程会变成孤儿进程！
    """
    global _process_pool, _warmup_future, _encoder_ready, _encoder_loading

    with _pool_lock:
        if _process_pool is not None:
            logger.info("[memory-mcp] Shutting down encoder process pool...")
            try:
                # 等待预热任务完成（如果还在运行）
                if _warmup_future is not None and not _warmup_future.done():
                    try:
                        _warmup_future.result(timeout=5.0)
                    except:
                        pass

                # 关闭进程池，等待子进程退出
                _process_pool.shutdown(wait=True, cancel_futures=True)
                logger.info("[memory-mcp] Encoder process pool shut down successfully")
            except Exception as e:
                logger.error(f"[memory-mcp] Error shutting down process pool: {e}")
            finally:
                _process_pool = None
                _warmup_future = None
                _encoder_ready = False
                _encoder_loading = False


# 兼容旧接口
def get_encoder(block: bool = True):
    """
    兼容旧接口 - 不再使用，仅用于检查状态
    """
    if _encoder_ready:
        return True  # 返回真值表示就绪
    if not block:
        return None
    raise RuntimeError("请使用 encode_text() 函数进行编码")


class VectorStore:
    """向量存储封装"""

    def __init__(self, db_path: str, collection_name: str = "default"):
        self.db_path = Path(db_path)
        self.db_path.mkdir(parents=True, exist_ok=True)

        # 先设置 SQLite WAL 模式（在 ChromaDB 打开之前）
        # WAL 模式允许多进程并发访问，解决数据库锁定问题
        try:
            import sqlite3
            db_file = self.db_path / "chroma.sqlite3"
            if db_file.exists():
                conn = sqlite3.connect(str(db_file), timeout=5.0)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.close()
        except Exception:
            pass  # 忽略错误，继续使用默认模式

        # 初始化 ChromaDB
        self.client = chromadb.PersistentClient(
            path=str(self.db_path),
            settings=Settings(anonymized_telemetry=False)
        )

        # 获取或创建集合
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )

    def add(
        self,
        doc_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """添加文档（使用进程池编码）"""
        vector = encode_text(content)

        self.collection.add(
            ids=[doc_id],
            embeddings=[vector],
            documents=[content],
            metadatas=[metadata or {}]
        )

        return doc_id

    def update(
        self,
        doc_id: str,
        content: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """更新文档"""
        update_kwargs = {"ids": [doc_id]}

        if content:
            vector = encode_text(content)
            update_kwargs["embeddings"] = [vector]
            update_kwargs["documents"] = [content]

        if metadata:
            update_kwargs["metadatas"] = [metadata]

        self.collection.update(**update_kwargs)

    def delete(self, doc_id: str):
        """删除文档"""
        self.collection.delete(ids=[doc_id])

    def search(
        self,
        query: str,
        top_k: int = 5,
        where: Optional[Dict] = None,
        include_distances: bool = False
    ) -> List[Dict]:
        """
        语义搜索

        内部会自动等待编码器就绪（如果正在初始化）
        """
        # 直接使用向量搜索，encode_text() 内部会确保编码器就绪
        return self._vector_search(query, top_k, where, include_distances)

    def _vector_search(
        self,
        query: str,
        top_k: int = 5,
        where: Optional[Dict] = None,
        include_distances: bool = False
    ) -> List[Dict]:
        """向量语义搜索（使用进程池编码）"""
        vector = encode_text(query)

        try:
            results = self.collection.query(
                query_embeddings=[vector],
                n_results=top_k,
                where=where,
                include=["documents", "metadatas", "distances"] if include_distances else ["documents", "metadatas"]
            )
        except Exception as e:
            error_msg = str(e)
            if "Error finding id" in error_msg or "finding id" in error_msg.lower():
                # 索引与元数据不同步，降级到关键词搜索
                logger.warning(f"向量索引可能损坏，降级到关键词搜索: {e}")
                return self._keyword_search(query, top_k, where)
            # 其他错误继续抛出
            raise

        # 格式化结果
        items = []
        for i in range(len(results["ids"][0])):
            item = {
                "id": results["ids"][0][i],
                "content": results["documents"][0][i],
                "metadata": results["metadatas"][0][i]
            }
            if include_distances:
                item["distance"] = results["distances"][0][i]
            items.append(item)

        return items

    def _keyword_search(
        self,
        query: str,
        top_k: int = 5,
        where: Optional[Dict] = None
    ) -> List[Dict]:
        """
        关键词匹配搜索（降级方案）

        使用 ChromaDB 的 where_document 进行简单文本匹配
        """
        # 提取查询中的关键词（简单分词）
        keywords = [w.strip() for w in query.split() if len(w.strip()) >= 2]

        # 获取所有文档，然后在内存中过滤
        results = self.collection.get(
            where=where,
            limit=top_k * 10,  # 获取更多以便过滤
            include=["documents", "metadatas"]
        )

        if not results["ids"]:
            return []

        # 按关键词匹配度排序
        scored_items = []
        for i in range(len(results["ids"])):
            content = results["documents"][i] or ""
            # 计算匹配分数：匹配到的关键词数量
            score = sum(1 for kw in keywords if kw.lower() in content.lower())
            if score > 0 or not keywords:  # 无关键词时返回全部
                scored_items.append({
                    "id": results["ids"][i],
                    "content": content,
                    "metadata": results["metadatas"][i],
                    "_score": score
                })

        # 按分数降序排序
        scored_items.sort(key=lambda x: x["_score"], reverse=True)

        # 移除内部分数字段，返回 top_k 个
        items = []
        for item in scored_items[:top_k]:
            del item["_score"]
            items.append(item)

        return items

    def get(self, doc_id: str) -> Optional[Dict]:
        """根据 ID 获取文档"""
        results = self.collection.get(
            ids=[doc_id],
            include=["documents", "metadatas"]
        )

        if not results["ids"]:
            return None

        return {
            "id": results["ids"][0],
            "content": results["documents"][0],
            "metadata": results["metadatas"][0]
        }

    def get_by_type(
        self,
        entity_type: str,
        limit: int = 10,
        status: str = "active"
    ) -> List[Dict]:
        """按类型获取实体"""
        results = self.collection.get(
            where={"$and": [{"type": entity_type}, {"status": status}]},
            limit=limit,
            include=["documents", "metadatas"]
        )

        items = []
        for i in range(len(results["ids"])):
            items.append({
                "id": results["ids"][i],
                "content": results["documents"][i],
                "metadata": results["metadatas"][i]
            })

        return items

    def count(self) -> int:
        """获取文档数量"""
        return self.collection.count()

    def list_all(self, limit: int = 100) -> List[Dict]:
        """列出所有文档"""
        results = self.collection.get(
            limit=limit,
            include=["documents", "metadatas"]
        )

        items = []
        for i in range(len(results["ids"])):
            items.append({
                "id": results["ids"][i],
                "content": results["documents"][i],
                "metadata": results["metadatas"][i]
            })

        return items
