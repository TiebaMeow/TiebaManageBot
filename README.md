<div align="center">

# TiebaManageBot

_基于 [Nonebot2](https://github.com/nonebot/nonebot2) 与 [aiotieba](https://github.com/lumina37/aiotieba) 的贴吧管理机器人_

</div>

## 简介

欢迎使用贴吧管理 bot，本 bot 旨在为吧主和各位吧务在吧务群内提供一种指令清晰、交互方便的贴吧管理方式，功能包括但不限于封禁拉黑等基础吧务操作、循封管理、申诉推送与处理、信息查询与录入等。

更多使用方法，欢迎查阅[使用手册](./docs/使用手册.md)。

注意：基于能用就行的思想，你可能会看到非常丑陋的代码实现。

## 安装依赖

1. 安装并启动 Mongodb

    - [Windows 平台安装 MongoDB](https://www.runoob.com/mongodb/mongodb-window-install.html)
    - [Linux 平台安装 MongoDB](https://www.runoob.com/mongodb/mongodb-linux-install.html)

    你也可以使用 Docker 安装 MongoDB，记得修改 `/your/local/path` 为你本地的路径：

    ```shell
    docker run -d -p 27017:27017 --name mongodb -v /your/local/path:/data/db mongo
    ```

2. 安装依赖

```shell
uv sync
```

## 运行

```shell
uv run nb run
```
