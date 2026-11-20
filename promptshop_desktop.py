"""PromptShop.exe の入口。exe を作るとき（build_exe.bat）に、PyInstaller へ渡す。"""
from app.desktop import main

if __name__ == "__main__":
    main()
