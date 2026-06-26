# Diet Delushan 正式上线部署说明

本文档覆盖当前项目上线需要的 MySQL、上传文件、体检报告、日志和备份策略。

## 1. 服务器目录

建议使用独立系统用户运行服务：

```bash
sudo useradd --system --home /var/www/diet-delushan --shell /usr/sbin/nologin diet
sudo mkdir -p /var/www/diet-delushan /var/lib/diet-delushan/uploads /var/log/diet-delushan /var/backups/diet-delushan
sudo chown -R diet:diet /var/www/diet-delushan /var/lib/diet-delushan /var/log/diet-delushan /var/backups/diet-delushan
```

运行时文件分层：

- `/var/lib/diet-delushan/uploads/bodyreport`：用户体检报告 PDF。
- `/var/lib/diet-delushan/uploads/picfile`：餐食图片。
- `/var/log/diet-delushan`：服务日志与备份任务日志。
- `/var/backups/diet-delushan`：MySQL 与上传文件备份。

## 2. MySQL

```sql
CREATE DATABASE diet_delushan CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'diet_app'@'localhost' IDENTIFIED BY 'replace_with_strong_password';
GRANT ALL PRIVILEGES ON diet_delushan.* TO 'diet_app'@'localhost';
FLUSH PRIVILEGES;
```

后端 `.env` 参考 `backend/.env.example`：

```env
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=diet_app
MYSQL_PASSWORD=replace_with_strong_password
MYSQL_DB=diet_delushan
CREATE_TABLES_ON_STARTUP=true
UPLOAD_ROOT_DIR=/var/lib/diet-delushan/uploads
LOG_DIR=/var/log/diet-delushan
BACKUP_ROOT_DIR=/var/backups/diet-delushan
```

当前项目还没有迁移工具，首次上线可以把 `CREATE_TABLES_ON_STARTUP=true` 打开让 SQLAlchemy 建表；表创建成功并验证可用后，建议改回 `false`，后续再补 Alembic 迁移。

生成生产密钥：

```bash
python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
```

## 3. 构建与服务

```bash
cd /var/www/diet-delushan
git clone https://github.com/ly-825/dite.git .

cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

前端生产构建：

```bash
cd /var/www/diet-delushan/frontend
npm install
VITE_API_BASE_URL= npm run build
```

安装 systemd 服务：

```bash
sudo cp /var/www/diet-delushan/deploy/systemd/diet-delushan.service /etc/systemd/system/diet-delushan.service
sudo systemctl daemon-reload
sudo systemctl enable --now diet-delushan
sudo systemctl status diet-delushan
```

安装 Nginx：

```bash
sudo cp /var/www/diet-delushan/deploy/nginx/diet-delushan.conf /etc/nginx/sites-available/diet-delushan.conf
sudo ln -s /etc/nginx/sites-available/diet-delushan.conf /etc/nginx/sites-enabled/diet-delushan.conf
sudo nginx -t
sudo systemctl reload nginx
```

把 `deploy/nginx/diet-delushan.conf` 里的 `server_name example.com` 改成真实域名。正式公网建议再接入 HTTPS，例如 Certbot。

## 4. 日志

服务日志优先使用 systemd journal：

```bash
journalctl -u diet-delushan -f
```

备份任务日志建议写到 `/var/log/diet-delushan/backup.log`。如果后续要做应用级 JSON 日志，可以直接复用 `.env` 中的 `LOG_DIR` 和 `LOG_FILE_NAME`。

## 5. 备份

安装备份脚本：

```bash
sudo cp /var/www/diet-delushan/deploy/scripts/backup_mysql_and_uploads.sh /usr/local/bin/diet-delushan-backup
sudo chmod +x /usr/local/bin/diet-delushan-backup
```

每天凌晨备份一次，保留 30 天：

```cron
15 3 * * * BACKUP_ROOT=/var/backups/diet-delushan UPLOAD_ROOT=/var/lib/diet-delushan/uploads MYSQL_HOST=127.0.0.1 MYSQL_PORT=3306 MYSQL_USER=diet_app MYSQL_PASSWORD='replace_with_strong_password' MYSQL_DB=diet_delushan RETENTION_DAYS=30 /usr/local/bin/diet-delushan-backup >> /var/log/diet-delushan/backup.log 2>&1
```

恢复 MySQL：

```bash
gunzip -c /var/backups/diet-delushan/mysql/diet_delushan_YYYYmmdd_HHMMSS.sql.gz \
  | mysql -h 127.0.0.1 -u diet_app -p diet_delushan
```

恢复上传文件：

```bash
sudo tar -xzf /var/backups/diet-delushan/uploads/uploads_YYYYmmdd_HHMMSS.tar.gz -C /var/lib/diet-delushan
sudo chown -R diet:diet /var/lib/diet-delushan/uploads
```
