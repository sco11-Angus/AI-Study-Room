"""后端启动入口 (§11)。生产部署使用 gunicorn。"""
from app import create_app

app = create_app()

if __name__ == "__main__":
    # Swagger 文档: http://localhost:5000/apidocs
    app.run(host="0.0.0.0", port=5000, debug=True)
