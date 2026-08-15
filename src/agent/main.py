"""
命令行测试入口
--------------
在 VS Code 终端中运行：
    python src/agent/main.py

可以交互式地和村寨代言人对话，快速验证 RAG 效果。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.rag import VillageAgent
from agent import config


def print_banner():
    """打印欢迎信息"""
    print("=" * 50)
    print("  红色村寨数字代言人 - Agent 测试")
    print("=" * 50)
    print(f"  模型: {config.MODEL_NAME}")
    print(f"  村寨: {', '.join(config.VILLAGES)}")
    print()
    print("  输入 'v 村寨名' 切换村寨（如: v 扎西）")
    print("  输入 'quit' 或 'exit' 退出")
    print("=" * 50)
    print()


def main():
    print_banner()

    # 初始化 Agent
    agent = VillageAgent()

    # 默认村寨
    village = "皎平渡"
    print(f"当前村寨: {village}\n")

    while True:
        try:
            # 读取用户输入
            user_input = input("你: ").strip()

            if not user_input:
                continue

            # 退出
            if user_input.lower() in ("quit", "exit", "q"):
                print("再见！")
                break

            # 切换村寨
            if user_input.lower().startswith("v "):
                new_village = user_input[2:].strip()
                if new_village in config.VILLAGES:
                    village = new_village
                    print(f"\n已切换到: {village}\n")
                else:
                    print(f"\n未知村寨，可选: {', '.join(config.VILLAGES)}\n")
                continue

            # 提问
            print(f"\n[{village}代言人] 思考中...")
            answer = agent.ask(user_input, village=village)
            print(f"\n[{village}代言人]: {answer}\n")

        except KeyboardInterrupt:
            print("\n\n再见！")
            break
        except Exception as e:
            print(f"\n[错误] {e}\n")


if __name__ == "__main__":
    main()
