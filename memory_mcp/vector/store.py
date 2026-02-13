"""
向量存储模块
使用 ChromaDB 作为向量数据库

优化策略：
1. 使用 subprocess.Popen 启动独立编码器工作进程
2. 通过显式创建的 stdin/stdout PIPE 通信，避免 MCP stdio 管道继承问题
3. 模型加载在子进程中，不占用主进程 GIL
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
import subprocess

logger = logging.getLogger(__name__)

# 模型配置
MODEL_NAME = 'paraphrase-multilingual-MiniLM-L12-v2'

# 全局状态
_encoder_ready = False
_encoder_loading = False
_encoder_lock = threading.Lock()

# 编码器子进程
_worker_proc: Optional[subprocess.Popen] = None
_worker_lock = threading.Lock()


def is_encoder_ready() -> bool:
    """检查编码器是否已加载完成"""
    return _encoder_ready


def is_encoder_loading() -> bool:
    """检查编码器是否正在加载中"""
    return _encoder_loading


def _get_worker_script() -> str:
    """获取 worker 脚本路径"""
    return str(Path(__file__).parent / "_encoder_worker.py")


def _start_worker():
    """启动编码器工作进程（在后台线程中调用）"""
    global _worker_proc, _encoder_ready, _encoder_loading

    with _encoder_lock:
        if _encoder_ready and _worker_proc and _worker_proc.poll() is None:
            return
        if _encoder_loading:
            return
        _encoder_loading = True

    try:
        worker_script = _get_worker_script()
        print(f"[memory-mcp] Starting encoder worker subprocess...", file=sys.stderr)

        kwargs = {
            'stdin': subprocess.PIPE,
            'stdout': subprocess.PIPE,
            'stderr': subprocess.PIPE,
            'cwd': str(Path(__file__).parent.parent.parent),
        }
        if sys.platform == 'win32':
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

        _worker_proc = subprocess.Popen(
            [sys.executable, worker_script, MODEL_NAME],
            **kwargs,
        )

        print(f"[memory-mcp] Worker pid={_worker_proc.pid}, waiting for model load...", file=sys.stderr)

        # 等待 worker 发送 ready（阻塞，在后台线程中运行所以 OK）
        first_line = _worker_proc.stdout.readline()
        if not first_line:
            stderr_out = _worker_proc.stderr.read().decode('utf-8', errors='replace')
            raise RuntimeError(f"Worker produced no output. stderr: {stderr_out[:500]}")

        resp = json.loads(first_line.decode('utf-8'))
        if "error" in resp:
            raise RuntimeError(f"Worker error: {resp['error']}")

        if resp.get("status") == "ready":
            _encoder_ready = True
            _encoder_loading = False
            print("[memory-mcp] Encoder worker ready!", file=sys.stderr)
        else:
            raise RuntimeError(f"Unexpected worker response: {resp}")

    except Exception as e:
        _encoder_loading = False
        print(f"[memory-mcp] Worker start failed: {e}", file=sys.stderr)
        logger.error(f"[memory-mcp] Worker start failed: {e}")
        # 清理
        if _worker_proc and _worker_proc.poll() is None:
            _worker_proc.kill()
        _worker_proc = None


def start_encoder_warmup():
    """启动编码器预热（非阻塞）"""
    threading.Thread(target=_start_worker, daemon=True, name="encoder-warmup").start()


def encode_text(text: str, timeout: float = 60.0) -> List[float]:
    """编码文本，编码器未就绪时直接抛出异常"""
    if not _encoder_ready:
        raise RuntimeError("向量编码器尚未就绪，请稍后再试。可运行 memory-mcp-init 预下载模型。")

    # 发送编码请求
    with _worker_lock:
        if _worker_proc is None or _worker_proc.poll() is not None:
            raise RuntimeError("编码器工作进程已退出")

        try:
            req = json.dumps({"text": text}) + "\n"
            _worker_proc.stdin.write(req.encode('utf-8'))
            _worker_proc.stdin.flush()

            resp_line = _worker_proc.stdout.readline()
            if not resp_line:
                raise RuntimeError("编码器无响应")

            resp = json.loads(resp_line.decode('utf-8'))
            if "error" in resp:
                raise RuntimeError(f"编码失败: {resp['error']}")

            return resp["vector"]
        except (BrokenPipeError, OSError) as e:
            raise RuntimeError(f"编码器通信失败: {e}")


def shutdown_encoder():
    """关闭编码器工作进程"""
    global _worker_proc, _encoder_ready, _encoder_loading

    if _worker_proc and _worker_proc.poll() is None:
        try:
            _worker_proc.stdin.write(b'{"cmd":"quit"}\n')
            _worker_proc.stdin.flush()
            _worker_proc.wait(timeout=5)
        except Exception:
            _worker_proc.kill()

    _worker_proc = None
    _encoder_ready = False
    _encoder_loading = False
    logger.info("[memory-mcp] Encoder shut down")


# 兼容旧接口
def get_encoder(block: bool = True):
    if _encoder_ready:
        return True
    if not block:
        return None
    raise RuntimeError("请使用 encode_text() 函数进行编码")


class VectorStore:
    """向量存储封装"""

    def __init__(self, db_path: str, collection_name: str = "default"):
        self.db_path = Path(db_path)
        self.db_path.mkdir(parents=True, exist_ok=True)

        try:
            import sqlite3
            db_file = self.db_path / "chroma.sqlite3"
            if db_file.exists():
                conn = sqlite3.connect(str(db_file), timeout=5.0)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.close()
        except Exception:
            pass

        self.client = chromadb.PersistentClient(
            path=str(self.db_path),
            settings=Settings(anonymized_telemetry=False)
        )

        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )

    def add(self, doc_id: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        vector = encode_text(content)
        self.collection.add(ids=[doc_id], embeddings=[vector], documents=[content], metadatas=[metadata or {}])
        return doc_id

    def update(self, doc_id: str, content: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
        update_kwargs = {"ids": [doc_id]}
        if content:
            vector = encode_text(content)
            update_kwargs["embeddings"] = [vector]
            update_kwargs["documents"] = [content]
        if metadata:
            update_kwargs["metadatas"] = [metadata]
        self.collection.update(**update_kwargs)

    def delete(self, doc_id: str):
        self.collection.delete(ids=[doc_id])

    def search(self, query: str, top_k: int = 5, where: Optional[Dict] = None, include_distances: bool = False) -> List[Dict]:
        return self._vector_search(query, top_k, where, include_distances)

    def _vector_search(self, query: str, top_k: int = 5, where: Optional[Dict] = None, include_distances: bool = False) -> List[Dict]:
        vector = encode_text(query)
        try:
            results = self.collection.query(
                query_embeddings=[vector], n_results=top_k, where=where,
                include=["documents", "metadatas", "distances"] if include_distances else ["documents", "metadatas"]
            )
        except Exception as e:
            error_msg = str(e)
            if "Error finding id" in error_msg or "finding id" in error_msg.lower():
                logger.warning(f"向量索引可能损坏，降级到关键词搜索: {e}")
                return self._keyword_search(query, top_k, where)
            raise

        items = []
        for i in range(len(results["ids"][0])):
            item = {"id": results["ids"][0][i], "content": results["documents"][0][i], "metadata": results["metadatas"][0][i]}
            if include_distances:
                item["distance"] = results["distances"][0][i]
            items.append(item)
        return items

    def _keyword_search(self, query: str, top_k: int = 5, where: Optional[Dict] = None) -> List[Dict]:
        keywords = [w.strip() for w in query.split() if len(w.strip()) >= 2]
        results = self.collection.get(where=where, limit=top_k * 10, include=["documents", "metadatas"])
        if not results["ids"]:
            return []

        scored_items = []
        for i in range(len(results["ids"])):
            content = results["documents"][i] or ""
            score = sum(1 for kw in keywords if kw.lower() in content.lower())
            if score > 0 or not keywords:
                scored_items.append({"id": results["ids"][i], "content": content, "metadata": results["metadatas"][i], "_score": score})

        scored_items.sort(key=lambda x: x["_score"], reverse=True)
        items = []
        for item in scored_items[:top_k]:
            del item["_score"]
            items.append(item)
        return items

    def get(self, doc_id: str) -> Optional[Dict]:
        results = self.collection.get(ids=[doc_id], include=["documents", "metadatas"])
        if not results["ids"]:
            return None
        return {"id": results["ids"][0], "content": results["documents"][0], "metadata": results["metadatas"][0]}

    def get_by_type(self, entity_type: str, limit: int = 10, status: str = "active") -> List[Dict]:
        results = self.collection.get(
            where={"$and": [{"type": entity_type}, {"status": status}]},
            limit=limit, include=["documents", "metadatas"]
        )
        items = []
        for i in range(len(results["ids"])):
            items.append({"id": results["ids"][i], "content": results["documents"][i], "metadata": results["metadatas"][i]})
        return items

    def count(self) -> int:
        return self.collection.count()

    def list_all(self, limit: int = 100) -> List[Dict]:
        results = self.collection.get(limit=limit, include=["documents", "metadatas"])
        items = []
        for i in range(len(results["ids"])):
            items.append({"id": results["ids"][i], "content": results["documents"][i], "metadata": results["metadatas"][i]})
        return items
