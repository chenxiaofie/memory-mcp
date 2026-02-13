"""
编码器工作进程

独立运行，通过 stdin/stdout 的 JSON 行与主进程通信。
协议：
  - 主进程发送: {"text": "..."} 或 {"texts": ["...", ...]}
  - 工作进程返回: {"vector": [...]} 或 {"vectors": [[...], ...]}
  - 工作进程就绪时发送: {"status": "ready"}
  - 错误时返回: {"error": "..."}
"""
import sys
import json
import os

def main():
    # 禁用进度条
    os.environ['HF_HUB_DISABLE_PROGRESS_BARS'] = '1'
    os.environ['TQDM_DISABLE'] = '1'

    model_name = sys.argv[1] if len(sys.argv) > 1 else 'paraphrase-multilingual-MiniLM-L12-v2'

    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(model_name)
    except Exception as e:
        sys.stdout.write(json.dumps({"error": f"model load failed: {e}"}) + "\n")
        sys.stdout.flush()
        return

    # 通知主进程模型已就绪
    sys.stdout.write(json.dumps({"status": "ready"}) + "\n")
    sys.stdout.flush()

    # 循环处理编码请求
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)

            if "text" in req:
                vec = model.encode(req["text"]).tolist()
                resp = {"vector": vec}
            elif "texts" in req:
                vecs = [v.tolist() for v in model.encode(req["texts"])]
                resp = {"vectors": vecs}
            elif req.get("cmd") == "quit":
                break
            else:
                resp = {"error": "unknown request"}

            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
        except Exception as e:
            sys.stdout.write(json.dumps({"error": str(e)}) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
