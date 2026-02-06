#!/usr/bin/env python3
"""
测试竞态条件修复：模拟 workflow 场景下的快速连续调用
"""
import sys
import time
from pathlib import Path

# 添加 src 到路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from vector import encode_text, is_encoder_ready, is_encoder_loading


def test_race_condition():
    """
    测试场景：模拟 workflow 框架的快速调用

    预期结果：即使在首次调用时编码器未就绪，也应该等待其就绪而不是抛出错误
    """
    print("=" * 60)
    print("测试竞态条件修复")
    print("=" * 60)

    # 场景 1：首次调用，编码器可能正在初始化
    print("\n[测试 1] 首次调用 encode_text()（可能触发编码器加载）")
    print(f"初始状态 - ready: {is_encoder_ready()}, loading: {is_encoder_loading()}")

    start = time.time()
    try:
        result = encode_text("测试文本 1")
        elapsed = time.time() - start
        print(f"[OK] 编码成功！耗时: {elapsed:.2f}s，向量维度: {len(result)}")
        print(f"编码后状态 - ready: {is_encoder_ready()}, loading: {is_encoder_loading()}")
    except Exception as e:
        elapsed = time.time() - start
        print(f"[FAIL] 编码失败！耗时: {elapsed:.2f}s")
        print(f"错误: {e}")
        print(f"失败后状态 - ready: {is_encoder_ready()}, loading: {is_encoder_loading()}")
        return False

    # 场景 2：立即第二次调用（模拟 workflow 连续调用）
    print("\n[测试 2] 立即第二次调用（模拟 workflow 连续调用）")
    start = time.time()
    try:
        result = encode_text("测试文本 2")
        elapsed = time.time() - start
        print(f"[OK] 编码成功！耗时: {elapsed:.2f}s，向量维度: {len(result)}")
    except Exception as e:
        elapsed = time.time() - start
        print(f"[FAIL] 编码失败！耗时: {elapsed:.2f}s")
        print(f"错误: {e}")
        return False

    # 场景 3：批量快速调用
    print("\n[测试 3] 批量快速调用（模拟 workflow 多次检索）")
    for i in range(5):
        start = time.time()
        try:
            result = encode_text(f"测试文本 {i+3}")
            elapsed = time.time() - start
            print(f"  调用 {i+1}: [OK] 耗时 {elapsed:.3f}s")
        except Exception as e:
            elapsed = time.time() - start
            print(f"  调用 {i+1}: [FAIL] 耗时 {elapsed:.3f}s, 错误: {e}")
            return False

    print("\n" + "=" * 60)
    print("[OK] 所有测试通过！竞态条件已修复")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = test_race_condition()
    sys.exit(0 if success else 1)
