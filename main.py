"""
FastAPI 应用入口

功能:
1. 创建 FastAPI 应用
2. 提供健康监控检查接口

"""

from fastapi import FastAPI

app = FastAPI()


@app.get("/")
async def root():
    """
    :return: 返回服务健康状态
    """
    return {"status": "ok"}
