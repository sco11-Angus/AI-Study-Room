"""统一API返回结构。"""


def ok(data=None, message="success"):
    """成功响应。"""
    return {
        "code": 0,
        "message": message,
        "data": data
    }


def err(message="error", code=1, data=None):
    """错误响应。"""
    return {
        "code": code,
        "message": message,
        "data": data
    }