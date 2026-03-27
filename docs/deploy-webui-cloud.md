# 云服务器 Web 界面访问指南

如果你已经把项目部署到云服务器，但不知道在浏览器里输入什么地址才能打开 Web 管理界面，这篇教程就是为你准备的。

> 其实就两步：让服务监听外网，再在浏览器里输入地址。

---

## 目录

- [方式一：直接部署（pip + python）](#方式一直接部署pip--python)
- [方式二：Docker Compose](#方式二docker-compose)
- [如何在浏览器里打开界面](#如何在浏览器里打开界面)
- [访问不了？先检查这几项](#访问不了先检查这几项)
- [可选：Nginx 反向代理（绑定域名 / 80 端口）](#可选nginx-反向代理绑定域名--80-端口)
- [安全建议](#安全建议)

---

## 方式一：直接部署（pip + python）

### 第一步：修改 .env 中的监听地址

用编辑器打开 `.env`（在项目根目录，即包含 `main.py` 的目录），找到这一行：

```env
WEBUI_HOST=127.0.0.1
```

把 `127.0.0.1` 改成 `0.0.0.0`：

```env
WEBUI_HOST=0.0.0.0
```

> `127.0.0.1` 表示只有本机能访问，`0.0.0.0` 表示允许任何来源访问。云服务器必须改成 `0.0.0.0` 才能从外网打开界面。

> **注意**：`.env` 里的 `WEBUI_HOST` 优先级高于命令行参数。所以即使你在命令里加了 `--host 0.0.0.0`，如果 `.env` 里还是 `127.0.0.1`，外网照样访问不了。请务必先改 `.env`。

### 第二步：启动服务

在项目根目录执行：

```bash
# 只启动 Web 界面（不自动执行分析）
python main.py --webui-only

# 或者：启动 Web 界面（启动时执行一次分析；需每日定时分析请加 --schedule 或设 SCHEDULE_ENABLED=true）
python main.py --webui
```

启动成功后，终端会输出类似：

```
FastAPI 服务已启动: http://0.0.0.0:8000
```

如果你想让服务在退出终端后继续运行，可以用 `nohup`：

```bash
nohup python main.py --webui-only > /dev/null 2>&1 &
```

> 日志文件会由程序自动写入 `logs/` 目录，用 `tail -f logs/stock_analysis_*.log` 查看。

### 修改端口（可选）

默认端口是 8000。如果想改用其他端口，在 `.env` 里设置：

```env
WEBUI_PORT=8888
```

然后重启服务。

---

## 方式二：Docker Compose

### 第一步：确认已有 .env 配置

项目的 `docker/docker-compose.yml` 在容器内部已经自动设置了 `WEBUI_HOST=0.0.0.0`，你不需要在 `.env` 里再改监听地址，Docker 会自动处理。

### 第二步：启动服务

在项目根目录执行：

```bash
# 同时启动定时分析 + Web 界面（推荐）
docker-compose -f ./docker/docker-compose.yml up -d

# 或者只启动 Web 界面服务
docker-compose -f ./docker/docker-compose.yml up -d server
```

启动后查看状态：

```bash
docker-compose -f ./docker/docker-compose.yml ps
```

看到 `server` 服务状态为 `running` 就说明 Web 界面已经在运行了。

### 修改端口（可选）

默认端口是 8000。如果想改用其他端口，在 `.env` 里设置：

```env
API_PORT=8888
```

然后重新启动容器：

```bash
docker-compose -f ./docker/docker-compose.yml down
docker-compose -f ./docker/docker-compose.yml up -d
```

---

## 如何在浏览器里打开界面

服务启动后，在浏览器地址栏输入：

```
http://你的服务器公网IP:8000
```

例如，如果你的服务器 IP 是 `1.2.3.4`，就输入：

```
http://1.2.3.4:8000
```

如果你的域名已经解析到这台服务器，也可以直接用域名访问：

```
http://your-domain.com:8000
```

> **在哪里查公网 IP？** 登录你的云服务器控制台（阿里云/腾讯云/AWS 等），在实例列表里可以看到「公网 IP」或「弹性 IP」。

---

## 访问不了？先检查这几项

### 1. 安全组 / 防火墙没有放行端口

这是最常见的原因。云服务器默认只开放 22（SSH）端口，需要手动放行 8000（或你改的端口）。

**操作方法**（以阿里云为例）：
1. 登录阿里云控制台 → 云服务器 ECS → 找到你的实例
2. 点击「安全组」→「配置规则」→「添加安全组规则」
3. 方向选「入方向」，端口范围填 `8000/8000`，授权对象填 `0.0.0.0/0`，点击「确定」

腾讯云、AWS 等云厂商操作类似，找到「安全组」或「防火墙规则」，新增一条允许 TCP 8000 端口的入站规则即可。

### 2. 服务器系统防火墙拦截了

如果你的系统开启了 `ufw` 或 `firewalld`，也需要放行端口：

```bash
# Ubuntu / Debian（ufw）
sudo ufw allow 8000

# CentOS / RHEL（firewalld）
sudo firewall-cmd --permanent --add-port=8000/tcp
sudo firewall-cmd --reload
```

### 3. 直接部署时 .env 里的 WEBUI_HOST 没改

这是第二常见原因。`.env` 里默认是 `WEBUI_HOST=127.0.0.1`，这样服务只监听本机，外网根本连不上。

改法：打开 `.env`，把 `WEBUI_HOST=127.0.0.1` 改成 `WEBUI_HOST=0.0.0.0`，然后重启服务。

> Docker 方式不需要改这个，可以跳过。

### 4. 端口号对不上

检查访问地址里的端口是否和 `.env` / 启动命令里设置的端口一致。

- 直接部署：默认 8000，可通过 `WEBUI_PORT=xxxx` 修改
- Docker：默认 8000，可通过 `API_PORT=xxxx` 修改

---

## 可选：Nginx 反向代理（绑定域名 / 80 端口）

如果你有域名，或者不想在地址里带 `:8000`，可以用 Nginx 做反向代理，把 80/443 端口流量转发给后端服务。

### 安装 Nginx

```bash
# Ubuntu / Debian
sudo apt update && sudo apt install -y nginx

# CentOS
sudo yum install -y nginx
```

### 配置文件示例

新建文件 `/etc/nginx/conf.d/stock-analyzer.conf`，内容如下（把 `your-domain.com` 改成你的域名或 IP）：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 支持 WebSocket（Agent 对话页面需要）
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### 启用配置并重启 Nginx

```bash
sudo nginx -t            # 检查配置有没有语法错误
sudo systemctl reload nginx
```

配置成功后，直接用 `http://your-domain.com` 访问即可，不需要带端口号。

> **使用 Nginx 后的注意事项**：
> - 如果你开启了 Web 登录认证（`ADMIN_AUTH_ENABLED=true`），建议在 `.env` 中把 `TRUST_X_FORWARDED_FOR=true` 一并打开，否则系统可能无法正确识别真实 IP。该选项适用于**单层可信反向代理**（Nginx → App）部署；如果使用多级代理或 CDN（CDN → Nginx → App），登录限流的 key 可能退化为边缘代理 IP 而非真实客户端 IP，需根据实际拓扑评估。
> - 如需 HTTPS，可以用 [Certbot](https://certbot.eff.org/) 自动申请免费的 Let's Encrypt 证书。

---

## 安全建议

把 Web 界面暴露到公网之前，强烈建议开启登录密码保护：

在 `.env` 中设置：

```env
ADMIN_AUTH_ENABLED=true
```

重启服务后，第一次访问网页时会要求设置初始密码。设置完成后，每次打开设置页面都需要输入密码，可以防止 API Key 等敏感配置被他人看到。

> 如果忘了密码，可以在服务器上执行：`python -m src.auth reset_password`

---

遇到其他问题？欢迎 [提交 Issue](https://github.com/ZhuLinsen/daily_stock_analysis/issues)。
