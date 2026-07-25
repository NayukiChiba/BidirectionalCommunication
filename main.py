"""
FastAPI 应用入口

功能:
1. 创建 FastAPI 应用
2. 提供健康监控检查接口

"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

app = FastAPI()


@app.get("/health")
async def get_health():
    """
    :return: 返回服务健康状态
    """
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """
    接受客户端的文本并且原样返回
    Args:
        websocket(WebSocket): websocket连接
    Returns:
        None
    """
    # 接受 WebSocket 握手
    await websocket.accept()

    try:
        while True:
            # 等待 websocket 接受文本
            message = websocket.receive_text()
            # 向 websocket 发送文本
            await websocket.send_text(message)
    except WebSocketDisconnect:
        # 客户端断开, 结束当前的连接
        return
