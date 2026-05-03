# EAlert Tracker 安装和使用指南

## 安装

### 方式 1：从 .skill 文件安装

```bash
# 将 ealert-tracker.skill 文件放到 Skills 目录
cp ealert-tracker.skill ~/.openclaw/skills/

# 或使用 OpenClaw CLI
openclaw skills install ealert-tracker.skill
```

### 方式 2：从源代码安装

```bash
# 克隆或复制到 Skills 目录
cp -r ealert-tracker ~/.openclaw/skills/

# 安装依赖
cd ~/.openclaw/skills/ealert-tracker
npm install
```

## 配置

### 第一步：配置 Gmail

1. **生成 App Password**
   - 访问 https://myaccount.google.com/apppasswords
   - 选择应用：Mail
   - 选择设备：Mac/Windows/Linux
   - 点击"生成"
   - 复制 16 位密码（格式：`xxxx xxxx xxxx xxxx`）

2. **创建 .env 文件**
   
   在 `imap-smtp-email` Skill 目录下创建 `.env`：
   
   ```bash
   # IMAP Configuration
   IMAP_HOST=imap.gmail.com
   IMAP_PORT=993
   IMAP_USER=your_email@gmail.com
   IMAP_PASS=xxxx xxxx xxxx xxxx
   IMAP_TLS=true
   IMAP_REJECT_UNAUTHORIZED=false
   
   # SMTP Configuration
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_SECURE=false
   SMTP_USER=your_email@gmail.com
   SMTP_PASS=xxxx xxxx xxxx xxxx
   SMTP_FROM=your_email@gmail.com
   SMTP_REJECT_UNAUTHORIZED=false
   ```

### 第二步：订阅期刊

访问以下网站订阅 Table of Contents 邮件：

- **Nature**: https://www.nature.com/nemail
- **Cell**: https://www.cell.com/alerts
- **Science**: https://www.science.org/action/showPreferences?menuTab=Alerts
- **Springer**: https://www.springer.com/gp/authors/alerts
- **Wiley**: https://onlinelibrary.wiley.com/

## 使用

### 手动运行

```bash
# 运行追踪（今天）
node scripts/tracker.js run

# 搜索最近 N 天
node scripts/tracker.js run --days 7

# 发送报告到邮箱
node scripts/tracker.js send-email --to target@email.com --file report.md
```

### 创建定时任务

使用 OpenClaw cron 创建每日任务：

```bash
# 每天早上 9:00 运行
openclaw cron add \
  --name "EAlert Tracker" \
  --schedule "0 9 * * *" \
  --timezone "Asia/Hong_Kong" \
  --message "运行 ealert-tracker 追踪期刊"
```

或在代码中：

```javascript
const { cron } = require('openclaw');

cron.add({
  name: "EAlert Tracker - 每日科研期刊追踪",
  schedule: { 
    kind: "cron", 
    expr: "0 9 * * *", 
    tz: "Asia/Hong_Kong" 
  },
  payload: { 
    kind: "agentTurn", 
    message: "运行 ealert-tracker，检查期刊邮件并生成报告" 
  },
  sessionTarget: "isolated"
});
```

## 输出

### 报告位置

```
ealert-tracker/reports/report_YYYY-MM-DD.md
```

### 报告格式

```markdown
# 📚 科研期刊追踪报告

**日期**: 2026-03-25
**监控期刊**: Nature, Cell, Science
**目标领域**: 生物信息学、计算生物学...

---

## 📊 今日精选 (N 篇)

### Nature

#### 1. 论文标题

| 项目 | 内容 |
|------|------|
| **期刊** | Nature |
| **摘要** | ... |
| **主要科学问题** | ... |
| **主要发现** | ... |
| **作者** | ... |
| **方法概述** | ... |
```

## 自定义配置

### 修改目标领域

编辑 `scripts/tracker.js`：

```javascript
const CONFIG = {
  targetFields: [
    // 添加或删除关键词
    'your-keyword',
    // ...
  ],
  journals: [
    // 添加或删除期刊
    'Your Journal',
    // ...
  ],
  emailKeywords: [
    // 邮件搜索关键词
    'Table of Contents',
    // ...
  ]
};
```

### 修改发送邮箱

在 `tracker.js` 中修改：

```javascript
const TARGET_EMAIL = 'your_target@email.com';
```

## 故障排除

### 问题 1：IMAP 连接失败

**错误信息**: `IMAP connection failed: Invalid credentials`

**解决方案**:
- 确认 App Password 正确（16 位，无空格）
- 确认 IMAP 已在 Gmail 设置中启用
- 检查 `.env` 文件中的 `IMAP_USER` 和 `IMAP_PASS`

### 问题 2：未找到论文

**原因**:
- 邮箱中没有期刊目录邮件
- 期刊还未发送最新目录
- 关键词不匹配

**解决方案**:
- 确认已订阅期刊
- 检查邮箱中是否有期刊邮件
- 修改 `CONFIG.targetFields` 中的关键词

### 问题 3：邮件发送失败

**错误信息**: `SMTP server error`

**解决方案**:
- 检查 SMTP 配置
- 确认 App Password 正确
- 检查目标邮箱地址是否正确

### 问题 4：证书错误

**错误信息**: `self-signed certificate`

**解决方案**:
- 在 `.env` 中设置 `IMAP_REJECT_UNAUTHORIZED=false`
- 在 `.env` 中设置 `SMTP_REJECT_UNAUTHORIZED=false`

## 常见问题

**Q: 可以追踪其他邮件服务吗？**
A: 可以。修改 `.env` 中的 `IMAP_HOST` 和 `SMTP_HOST` 为其他服务商的地址。

**Q: 可以追踪多个邮箱吗？**
A: 可以。创建多个 `.env` 文件或修改脚本以支持多邮箱。

**Q: 报告可以自动上传到云端吗？**
A: 可以。修改 `tracker.js` 中的 `sendEmail` 函数以支持云存储。

**Q: 可以生成 PDF 报告吗？**
A: 可以。使用 `pdf` Skill 将 Markdown 转换为 PDF。

---

**需要帮助？** 查看 SKILL.md 或 references/keywords.md
