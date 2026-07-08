"""简单启动脚本 - 仅启动Flask应用，不启动流调度器。"""
from app import create_app

app = create_app()

if __name__ == "__main__":
    print("=" * 50)
    print("Flask应用启动中...")
    print("访问地址:")
    print("  - API: http://localhost:5000/api/cameras")
    print("  - Swagger: http://localhost:5000/apidocs")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)