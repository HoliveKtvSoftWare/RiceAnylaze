# 模拟分析任务
def mock_analysis_function(filename: str, user_id: str):
    """
    一个模拟的后台任务函数。
    """
    print("--- RQ Worker 开始处理任务 ---")
    print(f"收到的文件名: {filename}")
    print(f"所属用户ID: {user_id}")
    print("...模拟处理中...")
    print("--- 任务处理完毕 ---")
    return True