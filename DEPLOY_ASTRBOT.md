# buff2steam 与 AstrBot Docker 部署

本方案假设 AstrBot 容器名为 `astrbot`，其宿主机数据目录为 `/opt/astrbot/data`。
若实际名称或目录不同，请替换命令中的对应值。

## 1. 准备内部网络

```bash
docker network create astrbot-internal || true
docker network connect astrbot-internal astrbot || true
```

不要将 buff2steam 的 `8080` 端口映射到公网。AstrBot 与 buff2steam 通过容器名互访。

## 2. 配置并启动服务

```bash
cp .env.buff2steam.example .env.buff2steam
openssl rand -hex 32
```

将生成的随机值写入 `BUFF2STEAM_SERVICE_TOKEN`，并填入具有 `im` 权限的
`ASTRBOT_API_KEY`。随后启动：

```bash
docker compose -f compose.buff2steam.yml pull
docker compose -f compose.buff2steam.yml up -d
docker exec buff2steam python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/healthz').read().decode())"
docker logs -f --tail=100 buff2steam
```

默认拉取 `docker.io/hitazuki/buff2steam:latest`。如需固定版本，将
`compose.buff2steam.yml` 中的 `image` 改为对应标签，例如
`docker.io/hitazuki/buff2steam:1.0.0`。普通运行参数直接维护在 Compose 的
`environment` 中；`.env.buff2steam` 仅保存 API Key 和服务令牌。

## 3. 安装 AstrBot 插件

```bash
mkdir -p /opt/astrbot/data/plugins/astrbot_plugin_buff2steam
cp -a astrbot_plugin_buff2steam/. /opt/astrbot/data/plugins/astrbot_plugin_buff2steam/
docker restart astrbot
```

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
docker compose -f compose.buff2steam.yml restart buff2steam
docker compose -f compose.buff2steam.yml down
```

数据库保存在命名卷 `buff2steam-data`，每日备份位于卷内 `/app/data/backups`，保留 7 天。

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
