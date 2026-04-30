# resource_filter

浏览器自动化抓取层，负责从目标站点进入灵感流或作者主页，依次打开作品详情，提取结构化信息后送进 `lunarsand_web` 的审核队列。

## 设计原则

- 站点适配器只关心页面动作和选择器，不关心存储。
- 持久化统一通过 `lunarsand_web` API 导入，这样 OSS 和数据库逻辑都收口在一处。
- 图片 OSS 上传也统一由 `lunarsand_web` 在导入时完成，爬虫侧只提交来源图片 URL。
- 同一抓取框架同时支持：
  - 灵感/首页抓取：记录详情 URL、prompt、作者、点赞、作者主页 URL。
  - 作者主页抓取：按作者主页继续依次抓取作品详情和 prompt。

## 当前适配器

- `jimeng`
- `xhs`
- `pose`
- `mj`
- `taobao`
- `jingdong`

## 安装

```bash
python -m pip install -r resource_filter/requirements.txt
playwright install chromium
```

## 运行前准备

确保 `lunarsand_web` 后端已经启动，并准备好：

- `LUNARSAND_API_BASE`
- `LUNARSAND_API_KEY`（可选，后端要求鉴权时再配置）

如果目标站点需要登录，优先推荐直接复用 Playwright 持久化用户目录 `--user-data-dir`。这些目录保存登录态和浏览器缓存，只应放在本地，不提交到仓库：

- [user_data/jimeng_profile](/mnt/d/project/resource_filter/user_data/jimeng_profile)：即梦登录态目录
- [user_data/xhs_profile](/mnt/d/project/resource_filter/user_data/xhs_profile)：小红书登录态目录
- [playwright/playwright_user_data](/mnt/d/project/resource_filter/playwright/playwright_user_data)：小红书原始 Playwright profile 目录

`--storage-state` 仍然可用，但更适合轻量会话复用；即梦这类站点优先建议走 `user_data`。
如果你需要补录小红书登录态，可以直接运行 [login_xhs.sh](/mnt/d/project/resource_filter/login_xhs.sh:1)，登录完成后回车即可保存到 `user_data/xhs_profile`。

## 启动脚本

推荐直接使用 [start_resource_filter.sh](/mnt/d/project/resource_filter/start_resource_filter.sh:1)：

```bash
cd /mnt/d/project/resource_filter
./start_resource_filter.sh
```

脚本支持两种方式：

- 不传参数：读取当前目录 `.env` 中的默认配置并启动。
- 直接传 CLI 参数：透传给 `python -m resource_filter.cli`。

`.env` 可配置项示例：

```bash
LUNARSAND_API_BASE=http://127.0.0.1:8000/api
LUNARSAND_API_KEY=your-api-key
RESOURCE_FILTER_SITE=jimeng
RESOURCE_FILTER_MODE=inspiration
RESOURCE_FILTER_ENTRY_URL=https://jimeng.jianying.com/ai-tool/home
RESOURCE_FILTER_KEYWORD=
RESOURCE_FILTER_TAB_LIMIT=1
RESOURCE_FILTER_TAB_NAMES=
RESOURCE_FILTER_AUTHOR_QUERY=
RESOURCE_FILTER_USER_DATA_DIR=/mnt/d/project/resource_filter/user_data/jimeng_profile
RESOURCE_FILTER_BROWSER_CHANNEL=chrome
RESOURCE_FILTER_HEADFUL=1
RESOURCE_FILTER_SLOW_MO=200
RESOURCE_FILTER_MAX_ITEMS=20
RESOURCE_FILTER_API_TIMEOUT=120
RESOURCE_FILTER_API_RETRIES=0
RESOURCE_FILTER_IMPORT_DELAY=2
RESOURCE_FILTER_STORAGE_STATE=/absolute/path/to/state.json
```

说明：

- 如果当前 shell 已激活 `conda` 或其他虚拟环境，`start_resource_filter.sh` 会优先使用当前环境里的 Python。
- 只有在没有激活环境时，脚本才会回退到项目目录下的 `.venv/bin/python`。
- `start_resource_filter.sh` 默认会优先使用 [user_data/jimeng_profile](/mnt/d/project/resource_filter/user_data/jimeng_profile)。
- `start_resource_filter.sh` 在 `--site xhs` 时会优先尝试 [user_data/xhs_profile](/mnt/d/project/resource_filter/user_data/xhs_profile)，不存在时再回退到 [playwright/playwright_user_data](/mnt/d/project/resource_filter/playwright/playwright_user_data)。
- `start_resource_filter.sh mj` 是 Midjourney 快捷入口，默认连接 `http://127.0.0.1:9222`，抓 `https://www.midjourney.com/explore?tab=top`，最多 60 条。
- `start_resource_filter.sh taobao` 是淘宝快捷入口，默认抓 `https://uland.taobao.com/sem/tbsearch`，关键词为 `古风衣服 汉服`，有头模式，最多 50 条。
- `start_resource_filter.sh jingdong` 是京东快捷入口，默认抓 `https://re.jd.com/search`，关键词为 `古风衣服 汉服`，有头模式，最多 50 条。
- `start_resource_filter.sh` 默认会优先使用系统 `chrome` 通道启动。
- `jimeng + inspiration` 模式下，如果你没显式传 `RESOURCE_FILTER_ENTRY_URL`，脚本会默认用 `https://jimeng.jianying.com/ai-tool/home`。
- `xhs + inspiration` 模式下，如果你没显式传 `RESOURCE_FILTER_ENTRY_URL`，脚本会默认用 `https://www.xiaohongshu.com/explore`。
- `RESOURCE_FILTER_USER_DATA_DIR` 存在时，会优先于 `RESOURCE_FILTER_STORAGE_STATE`。
- `RESOURCE_FILTER_API_TIMEOUT` 控制单次导入接口最长等待秒数；`RESOURCE_FILTER_API_RETRIES` 控制连接超时/中断重试次数，默认 `0` 表示不重试；`RESOURCE_FILTER_IMPORT_DELAY` 控制每条导入后的暂停秒数。
- 启动时会先复制一份临时 profile 再运行，结束后会把登录态相关文件同步回原始 `user_data`；这样既能避开锁文件，也不会丢掉你在运行窗口里更新过的登录状态。
- `xhs` 多图笔记会把首图作为 `source_image_url` 进入审核队列，完整图片列表会保存在 `raw_payload.detail.image_urls`。
- 爬虫会额外记录本地去重缓存：同站点下相同 `external_item_id` 且稳定详情快照未变化的内容，下次会直接跳过；如果 prompt、作者、详情字段或多图明细变化，则会重新走后端同步。

也可以直接传参数：

```bash
cd /mnt/d/project/resource_filter
./start_resource_filter.sh inspiration --entry-url "https://jimeng.jianying.com/ai-tool/home" --headful --slow-mo 200 --max-items 5
./start_resource_filter.sh --site xhs inspiration --keyword "武侠动作参考" --tab-limit 3 --max-items 5
./start_resource_filter.sh --site xhs author --author-query "橘困（努力拍照中）"
./start_resource_filter.sh mj
./start_resource_filter.sh mj --max-items 30
./start_resource_filter.sh taobao
./start_resource_filter.sh taobao "古风衣服 汉服"
./start_resource_filter.sh jingdong
./start_resource_filter.sh jd "古风衣服 汉服"
```

## CLI 用法

从灵感流抓取：

```bash
cd /mnt/d/project
python -m resource_filter.cli inspiration \
  --entry-url "https://jimeng.jianying.com/ai-tool/home" \
  --api-base "http://127.0.0.1:8000/api" \
  --api-key "your-api-key" \  # 可选
  --browser-channel "chrome" \
  --user-data-dir "/mnt/d/project/resource_filter/user_data/jimeng_profile"
```

从作者主页抓取：

```bash
cd /mnt/d/project
python -m resource_filter.cli author \
  --author-url "https://jimeng.jianying.com/your-author-page" \
  --api-base "http://127.0.0.1:8000/api" \
  --api-key "your-api-key" \  # 可选
  --browser-channel "chrome" \
  --user-data-dir "/mnt/d/project/resource_filter/user_data/jimeng_profile"
```

从小红书搜索结果抓取：

```bash
cd /mnt/d/project
python -m resource_filter.cli --site xhs inspiration \
  --keyword "武侠动作参考" \
  --tab-limit 3 \
  --max-items 5 \
  --api-base "http://127.0.0.1:8000/api" \
  --api-key "your-api-key" \  # 可选
  --browser-channel "chrome" \
  --user-data-dir "/mnt/d/project/resource_filter/user_data/xhs_profile"
```

从小红书作者页抓取：

```bash
cd /mnt/d/project
python -m resource_filter.cli --site xhs author \
  --author-query "橘困（努力拍照中）" \
  --api-base "http://127.0.0.1:8000/api" \
  --api-key "your-api-key" \  # 可选
  --browser-channel "chrome" \
  --user-data-dir "/mnt/d/project/resource_filter/user_data/xhs_profile"
```

常用参数：

- `--headful`：有头模式，便于调试。
- `--slow-mo 200`：减慢点击和跳转，便于观察。
- `--max-items 20`：限制本次最多抓取 20 张；`xhs inspiration` 下表示每个标签最多抓取 20 张。
- `--browser-channel chrome`：优先使用系统 Chrome/Edge 通道。
- `--user-data-dir /path/to/profile`：复用浏览器用户目录，适合站点登录态复用。
- `--storage-state /path/to/state.json`：复用登录态。
- `--keyword "武侠动作参考"`：`xhs inspiration` 的搜索关键词。
- `--tab-limit 3`：`xhs inspiration` 下最多切换 3 个搜索标签。
- `--tab-names 综合,张力,素材`：`xhs inspiration` 下按指定标签顺序抓取。
- `--author-query "作者名"`：`xhs author` 下按作者名称检索并进入主页。
