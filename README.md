<div align="center">

# TiebaManageBot

_基于 [Nonebot2](https://github.com/nonebot/nonebot2) 与 [aiotieba](https://github.com/lumina37/aiotieba) 的贴吧管理机器人_

</div>

## 简介

欢迎使用贴吧管理 bot，本 bot 旨在为吧主和各位吧务在吧务群内提供一种指令清晰、交互方便的贴吧管理方式，功能包括但不限于封禁拉黑等基础吧务操作、循封管理、申诉推送与处理、信息查询与录入等。

更多使用方法，欢迎查阅[使用手册](./docs/使用手册.md)。

关于高级功能的部署和使用，欢迎查阅[高级功能](./docs/高级功能.md)。

## 环境配置

1. 安装依赖

    `uv` 的安装方式详见[官方文档](https://docs.astral.sh/uv/getting-started/installation/)或[中文文档](https://hellowac.github.io/uv-zh-cn/getting-started/installation/)。

    ```shell
    uv sync
    ```

2. 安装 `playwright` 所需无头 `Chromium`

    ```shell
    uv run playwright install chromium-headless-shell
    ```

3. 根据注释修改项目根目录下 `.env` 文件中的配置项。

4. 安装并配置 NapCat

    具体部署方法参照 [NapCat](https://napneko.github.io/) 官方步骤。Windows 用户推荐使用 [NapCat.Win.一键版本](https://napneko.github.io/guide/boot/Shell#napcat-win-%E4%B8%80%E9%94%AE%E7%89%88%E6%9C%AC)。

    运行 `NapCat` 后，使用浏览器访问 `http://localhost:6099/webui`，登录页默认 token 会在 `NapCat` 的运行日志中输出，请注意查看。

    扫码登录后，点击 `网络配置` -> `新建` -> `Websocket客户端`，打开 `启用` 开关，填入任意自定义名称，在 `URL` 栏填写 `ws://localhost:18765/onebot/v11/ws`，点击保存。`NapCat` 的 `WebUI` 配置方法可参考 [NapCat 基础配置](https://napneko.github.io/config/basic)。

    如果需要，上面两个 localhost 可以替换为你的电脑/服务器 IP 地址。

    TiebaManageBot 同样支持其他实现了 OneBot 协议的 QQ 客户端，如 [LuckyLilliaBot](https://github.com/LLOneBot/LuckyLilliaBot) 等。`Websocket URL` 同上。

## 运行

```shell
uv run nb run
```

等待输出中出现 `[INFO] nonebot | OneBot V11 | Bot 123456789 connected` 即为成功连接到 QQ 客户端。

## Docker 部署

1. 根据实际环境修改 `.env` 文件中的相关配置。
2. 启动服务： `docker compose up -d`。
3. 查看运行日志：`docker compose logs -f bot`。
4. 停止服务：`docker compose down`。

`docker-compose.yml` 中并不包含 NapCat 服务，请确保你已经单独部署并配置好 NapCat 或其他，也可以将其编排到 `docker-compose.yml` 文件中。

高级功能的 Docker 部署请参考[高级功能](./docs/高级功能.md)文档。
