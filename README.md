# 崩铁抽卡统计

《崩坏：星穹铁道》本地抽卡（跃迁）记录统计工具。Windows 桌面程序，记录只存在自己电脑上，不上传任何服务器。

## 功能

- **一键更新记录**：自动从游戏缓存里找到跃迁记录链接，不用抓包、不用跑脚本；找不到时也可以手动粘贴链接（整段文字直接贴，自己挑出链接）
- **增量拉取、本地累积**：官方接口只能查到约一年的记录，工具把拉到的记录存在本地，越攒越全
- **保底与 UP 统计**：当前已抽数、每个五星用了多少抽、歪没歪、大保底
  - 角色池的歪池可以按自己在「星缘相邀」里选的角色设置（3.2 版本起的机制）
  - 判断有误时可以右键手动标记
- **头像墙**：按时间排列所有五星，带抽数和歪章
- **海报模式**：五星角色 / 光锥海报左右滑动浏览，可按卡池任意组合筛选
- **每月抽数柱状图**：各卡池叠在一起显示
- 支持 角色 / 光锥 / 常驻 / 新手 / 联动 跃迁，多个 UID 切换

## 下载使用（不用装 Python）

1. 到 [Releases](../../releases) 下载最新的 `hsr-gacha-stats-v<版本>.zip`，解压到任意文件夹
2. 在游戏里打开一次「跃迁」→「查看详情」里的跃迁记录（让游戏把记录链接存进缓存）
3. 双击 `抽卡统计.exe`，点右上角「**更新记录**」

以后想看最新记录，都是先在游戏里打开一下跃迁记录，再点「更新记录」。

### 说明

- 角色和光锥的图片第一次会自动下载（需要联网），每个角色十几秒，在后台慢慢生成
- 「图片文件夹」→ `自定义` 里可以放自己喜欢的图，替换海报（`名字.jpg`）和头像（`名字_头像.png`）
- 记录存在 exe 旁边的 `data` 文件夹里；换电脑或升级新版时，把 `data` 拷过去就行
- 跃迁记录链接（含 authkey）只在点「更新记录」时用一下，不会保存
- 请求米哈游接口一律直连，开着代理也能用

## 从源码运行

Windows，开发和测试用的是 Python 3.14。

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python app.py
```

### 自己打包 exe

```bash
.venv\Scripts\pip install pyinstaller
.venv\Scripts\python build.py
```

生成 `dist\崩铁抽卡统计\`（双击里面的 `抽卡统计.exe`）和压缩包 `dist\hsr-gacha-stats-v<版本>.zip`。只打包代码和自带资源，`data\`、`图片\`、`settings.json` 等个人数据不会进去。

## 代码结构

| 文件 | 作用 |
| --- | --- |
| `app.py` | 主窗口：总览 / 各卡池 / 海报模式 |
| `gacha_api.py` | 从游戏缓存找跃迁链接，按卡池分页拉取记录 |
| `store.py` | 本地记录 `data/<uid>.json`，按 id 去重合并 |
| `stats.py` | 保底计数、五星抽数、歪 / 不歪 / 大保底判断 |
| `images.py` | 下载并生成头像、海报（带背景的立绘裁切） |
| `posters.py` | 头像墙和海报模式 |
| `charts.py` | 每月抽数柱状图 |
| `fluent_ui.py` | 界面公共部分（基于 PySide6-Fluent-Widgets） |
| `standard.json` | 常驻光锥名单 |
| `build.py` | 打包脚本 |

## 致谢

- 界面：[PySide6](https://doc.qt.io/qtforpython-6/)、[PySide6-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)
- 图片素材：[Mar-7th/StarRailRes](https://github.com/Mar-7th/StarRailRes)、[enka.network](https://enka.network/)、[BWIKI 崩坏：星穹铁道](https://wiki.biligame.com/sr/)

## 声明

本项目是玩家自制工具，与米哈游无关。游戏内图片、名称等素材版权归米哈游所有。
