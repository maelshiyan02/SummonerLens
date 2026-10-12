# A05 · 工作空间与 Git 纪律

> 上级索引：`MEMORY.md` §1（A05）｜触发时机：碰 git、远程、目录、系统配置之前｜相关：A01 身份、A06 记忆

## 1. 工作空间根目录

- **根目录**：`<项目根>`（项目结构最初在独立目录初始化；2026-10-12 迁入「AI Coding Project Management」大工作区）。
- 🔴 **根目录将来可能改名** ⇒ 一切引用用**相对路径**（`SummonerLens/…`、`.agent/…`），**绝不写 `D:\…` / `C:\…`**；脚本由自身位置推导根目录。

## 2. Git 与远程（与 mangrove 严格隔离）

- **本地**：`git init`（本对话已完成）。
- **GitHub 仓库**：`SummonerLens`（maelshiyan02），**独立全新仓库**。
- 🔴 **remote 固定 SSH，绝不 HTTPS**（凭据链路已根治为 SSH，HTTPS 会重新引入弹窗风险）：
  ```
  git remote add origin git@github.com:maelshiyan02/SummonerLens.git
  ```
- **SSH 双通道（已就绪）**：
  - `github.com`（22 端口直连，**主用**）；
  - `github-443`（22 被干扰时切换，无需重配）：
    ```
    git remote set-url origin git@github-443:maelshiyan02/SummonerLens.git
    ```
- **隔离**：本项目与大工作区内同级目录 `../Mangrove` 是不同仓库/工作区/记忆体系，禁止互相改文件。

## 3. Git 操作纪律

- 🔴 **远程仓库未建前不要 `git push`**；建仓后首个动作 = `git remote add origin …` 并 `ssh -T git@github.com` 验证。
- **改 git 配置前先 `cp` 备份**（备份文件名带日期）。
- **改系统目录用改名替代删除**（保留回滚路径），勿直接 `rm`。
- 本仓库 `.gitignore` 已排除 `.workbuddy/`、构建产物、大数据集、密钥；**项目记忆 `.agent/` 入库**（共享记忆真身）。

## 4. 当前状态（2026-10-11）

- 工作区已 `git init`；GitHub 仓库 `SummonerLens` 待创建（gh 已登录 maelshiyan02，SSH 认证通过）。
- 待办：gh 建仓 → remote add（SSH）→ `ssh -T` 验证 → 首提交 `.agent/` 骨架 + README + 计划书 → push `main`。
