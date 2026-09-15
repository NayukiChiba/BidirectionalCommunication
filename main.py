"""容器和单机模式共用的应用启动入口。"""

from bootstrap import create_app, createStandaloneApp, runStandaloneApp

if __name__ == "__main__":
    app = createStandaloneApp(forceLocalServices=True)
    runStandaloneApp(app)
else:
    app = create_app()
