# buff2steam 与 AstrBot Docker 部署

AstrBot 请按 [官方仓库](https://github.com/AstrBotDevs/AstrBot)和
[官方 Docker 部署文档](https://docs.astrbot.app/deploy/astrbot/docker.html)
独立部署。AstrBot 与 buff2steam 应放在不同目录，各自维护自己的
`compose.yml`。

## 1. 准备内部网络

```bash
docker network create astrbot-internal || true
```

在官方 AstrBot Compose 中，将 `astrbot-internal` 加入 `astrbot` 服务，并在
顶层声明为外部网络；已有其他网络时保留原配置：

```yaml
services:
  astrbot:
    networks:
      - astrbot-internal

networks:
  astrbot-internal:
    external: true
```

不要只依赖 `docker network connect`，否则 AstrBot 容器重建后额外连接可能丢失。

不要将 buff2steam 的 `8080` 端口映射到公网。AstrBot 与 buff2steam 通过容器名互访。

## 2. 配置并启动服务

```bash
cp .env.buff2steam.example .env.buff2steam
openssl rand -hex 32
```

将生成的随机值写入 `BUFF2STEAM_SERVICE_TOKEN`，并填入具有 `im` 权限的
`ASTRBOT_API_KEY`。随后启动：

```bash
docker compose pull
docker compose up -d
docker exec buff2steam python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/healthz').read().decode())"
docker logs -f --tail=100 buff2steam
```

默认拉取 `docker.io/hitazuki/buff2steam:latest`。如需固定版本，将
`compose.yml` 中的 `image` 改为对应标签，例如
`docker.io/hitazuki/buff2steam:1.0.0`。普通运行参数直接维护在 Compose 的
`environment` 中；`.env.buff2steam` 仅保存 API Key 和服务令牌。

## 3. 安装 AstrBot 插件

```bash
ASTRBOT_DATA_DIR=/path/to/astrbot/data
mkdir -p "$ASTRBOT_DATA_DIR/plugins/astrbot_plugin_buff2steam"
cp -a astrbot_plugin_buff2steam/. "$ASTRBOT_DATA_DIR/plugins/astrbot_plugin_buff2steam/"
docker restart astrbot
```

`ASTRBOT_DATA_DIR` 必须是 AstrBot Compose 中挂载到 `/AstrBot/data` 的宿主机
目录。可用以下命令核对当前容器实际挂载：

```bash
docker inspect astrbot --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}'
```

迁移 AstrBot 目录前先停止容器，并整体复制数据目录。除 `config`、`plugins`、
`plugin_data` 外，SQLite 的主文件、`-wal` 和 `-shm` 必须作为同一组迁移；
不要将两个已经分别运行过的数据目录直接合并。

在 AstrBot WebUI 的插件配置中填写：

- `service_base_url`: `http://buff2steam:8080`
- `service_token`: 与 `BUFF2STEAM_SERVICE_TOKEN` 完全一致
- `timeout_seconds`: `10`

## 4. 验收

在 QQ 官方机器人会话中依次执行：

```text
/skin watch test
/skin watch add 1579 72
/skin quote 1579
/skin watch list
/skin watch status
```

`watch test/add/remove/threshold/status` 需要发送者已加入 AstrBot 管理员列表。

## 5. 运维

```bash
docker logs --tail=200 buff2steam
docker inspect --format='{{json .State.Health}}' buff2steam
docker compose restart buff2steam
docker compose down
```

数据库保存在部署目录的 `./data/monitor.db`，每日备份位于
`./data/backups`，保留 7 天。容器以 UID `10001` 运行，首次启动前创建并授权目录：

```bash
mkdir -p data
sudo chown -R 10001:10001 data
sudo chmod 750 data
```

## 6. DockerHub 自动发布

`.github/workflows/docker.yml` 会构建并发布 `linux/amd64`、`linux/arm64`
镜像。首次运行前，在 GitHub 仓库的
`Settings → Secrets and variables → Actions` 中添加：

- `DOCKERHUB_USERNAME`：DockerHub 用户名。
- `DOCKERHUB_TOKEN`：具有目标仓库 Read & Write 权限的访问令牌。

推送 `v*` 标签会自动发布去掉 `v` 的版本标签和 `latest`：

```bash
git tag v1.0.0
git push origin v1.0.0
```

以上操作会发布：

```text
docker.io/hitazuki/buff2steam:1.0.0
docker.io/hitazuki/buff2steam:latest
```

也可以在 GitHub Actions 页面手动运行。关闭 `push_image` 时仅验证构建，
不登录或推送 DockerHub；开启时发布 `dev` 和 `latest`。
升级前应额外导出该卷或复制最新备份。停止服务不会删除数据；不要执行带 `-v` 的 `down`。
