# 打包给别人用：.venv\Scripts\python.exe build.py
# 生成 dist\崩铁抽卡统计\（双击里面的 抽卡统计.exe 就能用，不用装 Python），再压成 dist\hsr-gacha-stats-v<版本>.zip。
# 只打包代码和自带的 standard.json、图标；data\、图片\、settings.json 这些个人数据不会进去。
import os, re, shutil, subprocess, sys, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = '崩铁抽卡统计'
VERSION = re.search(r"VERSION = '([^']+)'", open(os.path.join(HERE, 'app.py'), encoding='utf-8').read())[1]
DIST = os.path.join(HERE, 'dist')
OUT = os.path.join(DIST, NAME)
README = f"""崩铁抽卡统计 v{VERSION}

用法：
  1. 先在游戏里打开一次「跃迁」→「查看详情」里的跃迁记录（让游戏把记录链接存到缓存里）
  2. 双击「抽卡统计.exe」，点右上角「更新记录」
  以后每次想看最新的记录，都是先在游戏里打开一下跃迁记录，再点「更新记录」。
  自动找不到链接时，可以点「粘贴链接」把跃迁记录的链接（或含链接的整段文字）贴进去。

说明：
  · 官方接口只能查到大约最近一年的记录；工具会把拉到的记录存在旁边的 data 文件夹里，以后越攒越全。
  · 角色和光锥的图片第一次会自动下载（需要联网），每个角色要十几秒，后台慢慢生成。
  · 「图片文件夹」按钮里的「自定义」文件夹可以放自己喜欢的图替换海报和头像。
  · 换电脑或升级新版时，把 data 文件夹拷过去就行。
  · 记录链接只在点「更新记录」时用一下，不会保存。
"""


def res(name):
    return os.path.join(HERE, name)


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    subprocess.run([sys.executable, '-m', 'PyInstaller', res('app.py'), '--name', '抽卡统计', '--noconfirm', '--windowed',
                    '--icon', res('icon.ico'), '--add-data', res('icon.ico') + ';.', '--add-data', res('standard.json') + ';.',
                    '--distpath', OUT, '--workpath', os.path.join(HERE, 'build'), '--specpath', os.path.join(HERE, 'build'),
                    '--contents-directory', '运行库'], cwd=HERE, check=True)
    # PyInstaller 会多套一层 dist\崩铁抽卡统计\抽卡统计\，挪上来
    inner = os.path.join(OUT, '抽卡统计')
    for f in os.listdir(inner):
        shutil.move(os.path.join(inner, f), OUT)
    os.rmdir(inner)
    with open(os.path.join(OUT, '使用说明.txt'), 'w', encoding='utf-8-sig') as f:
        f.write(README)
    zip_path = os.path.join(DIST, f'hsr-gacha-stats-v{VERSION}.zip')    # GitHub Releases 的附件名不能有中文
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(OUT):
            for f in files:
                p = os.path.join(root, f)
                z.write(p, os.path.relpath(p, DIST))
    print(f'\n完成：{zip_path}（{os.path.getsize(zip_path) / 2**20:.0f} MB）')


if __name__ == '__main__':
    main()
