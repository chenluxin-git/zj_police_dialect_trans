# 浙警智治 · 内网对接信息采集工具（recon）

回答一个问题：**上架联调前，哪些信息只能在内网拿到，怎么拿才既有效又不出事。**

## 一、先想清楚：三类信息，三种拿法

联调卡住的信息只有三类，**混在一起做「尽可能收集」的脚本是效率最低的做法**：

| 类别 | 例子 | 正确拿法 | 本工具是否覆盖 |
| --- | --- | --- | --- |
| 平台侧信息 | AK/SK、系统标准码/requestId、三个服务地址、上架时选的「认证参数」类型、组件调用文档、siteId | **问对接人 / 看资源管理器**（`docs/zhijing-integration-request.md` 已写好话术） | ❌ 脚本问不出来 |
| 协议侧信息 | 回调实际传哪些参数名、`getLoginUser` 实际返回哪些字段、前置代理有没有吞 `RZZX-*` 头、`SFZH` 到底是不是身份证号 | **被动接收真实回调 + 代调接口落原始报文** | ✅ `serve` + `report`（**最高价值**） |
| 环境侧信息 | 到服务地址的连通性、服务端证书链（决定 `ZHIJING_VERIFY_SSL`）、时钟偏差、浏览器与证书介质 | 只读体检 | ✅ `check` / `token` / `auditstats` / 客户端脚本 |

**核心原则：被动优先。** 在公安网里，「平台打我们」比「我们打平台」既安全又确定——
主动扫描既容易触发态势感知，也**猜不出**平台的字段口径。

## 二、工具构成

```
scripts/zhijing-recon/
├── zhijing_recon.py              单文件、纯标准库（Python 3.8+），5 个子命令
├── zhijing-client-inventory.ps1  Windows 终端与证书介质盘点（只读，PS 5.1 兼容）
└── README.md                     本文件
```

## 三、哪里跑什么（重要）

| 子命令 / 脚本 | 跑在哪 | 为什么 |
| --- | --- | --- |
| `serve` + `report` | **应用服务器**（或平台回调可达的机器） | 要接平台回调和 `getLoginUser`，必须内网可达 |
| `check` | **应用服务器** | 关心的是这台机器的出网策略与到服务地址的连通性 |
| `token` | **应用服务器** | 验证 AK/SK 与 SM3 签名，需连认证服务 |
| `auditstats` | **应用服务器**（读本应用审计库） | 统计本系统实际登录认证因子 |
| `zhijing-client-inventory.ps1` | **民警/开发者终端（Windows）** | 浏览器版本与证书介质在客户端，不在服务器 |

## 四、用法

### 1) 环境体检：连通性 + 服务端证书链 + 时钟偏差

```bash
python zhijing_recon.py check --out ./recon-out
# 只测自己的地址（不测文档地址）：
python zhijing_recon.py check --url https://your.app.gat.zj --out ./recon-out
```

- **只连接下表列出的文档地址**，不做端口扫描、不做目录探测。
- 产出 `check-<ts>.json` / `check-<ts>.md`。

**它解决什么**：`config.py` 里 `zhijing_verify_ssl` 默认 `False`（注释写的是「内网自签/私有 CA，默认不校验」）。
**上架安全检测与三高一弱风险评估大概率会挑「传输未校验服务端证书」**——报告里的
`受信校验` 与 `SHA256` 就是拿来决定「把私有 CA 装进镜像后开启校验」还是「必须书面说明」的依据。

### 2) 被动回调观测器（最高价值）

```bash
python zhijing_recon.py serve --port 8600 \
    --rz-url https://lxrdl.gat.zj:5010/jiRMS_RzSer \
    --dqxtbs <系统标准码> --out ./recon-out
```

1. 把上架时填的**认证URL**临时指向本服务（`http://<服务器>:8600/`，或经 nginx 映射一个路径）；
2. 从浙警智治终端**点开应用**，让平台真实回调过来；
3. 抓够样本后 `Ctrl+C`，再汇总：

```bash
python zhijing_recon.py report --out ./recon-out
```

**它一次钉死四件事**：

| 报告章节 | 回答的问题 |
| --- | --- |
| §1 令牌传输方式 | 前置代理有没有吞 `RZZX-USERTOKEN`/`RZZX-APPTOKEN`（规范首选 Header）——这是联调报 `1001/1003` 的头号原因 |
| §2 回调参数名 | **动态秘钥**到底传哪些参数名（`dynamic_identity()` 现在是一串别名猜测，只能靠真实报文定死） |
| §3 认证因子候选 | 审计 `operateName` 该写「数字证书」还是「数字证书\|\|人脸认证」 |
| §4 字段核对 | `getLoginUser` 11 个字段是否齐全；**`SFZH` 是 18 位身份证号还是 32 位证书主体标识** |

> §4 的依据：文档 `getDetailedUser` 示例里 `IDCARD` 是 `A2B260A85D6444C9AE433F66DDA5D8F3`
> 这种 **32 位证书主体标识**，且有 `ISZSSFZ`（是否正式身份证）。规范允许审计 `userId`
> 填「公民身份号码**或**数字证书主体标识符」，但本地 `users.phone` 唯一列的取值口径要相应确认。

### 3) AK/SK 与 SM3 签名自证

```bash
python zhijing_recon.py token --ak <AppKey> --sk <SecretKey> --sys-id <系统标准码> --out ./recon-out
```

依次调用：应用令牌生成 → 应用令牌元素查询 → 应用令牌校验 → **令牌续期（SM3 `callerSign`）**。

**这是联调前唯一能自证「我方 SM3 签名拼接与规范一致」的手段**——
等真机联调才发现签名算法不对，排查成本高得多。返回 `0000/1004/1005` 即视为签名被平台接受。

### 4) 本地审计台账统计（谁在用、用哪种认证因子）

```bash
python zhijing_recon.py auditstats --db server/data/app.db --out ./recon-out
```

统计 `audit_logs` 里 `operate_type=0` 的 `operate_name` 分布、上报状态、12 位机构代码样本、真实源 IP 样本。

> **口径说明**：这只是**我们自己台账**，只能证明「流经本系统的登录」。
> 「全省/全市谁在用电子证书」的全域分布**必须向平台侧（统一认证/警综）索取**，本工具给不了。

### 5) 终端与证书介质盘点（Windows 客户端）

```powershell
powershell -ExecutionPolicy Bypass -File .\zhijing-client-inventory.ps1 -Out .\recon-out
```

产出 `client-inventory-<ts>.json` / `.md`：操作系统与**时钟同步**、Chrome/Edge 版本
（对照上架硬要求 **Chrome80**）、证书类客户端/中间件、**证书存储**（主体/签发者/有效期/指纹/是否带私钥）、
代理与 hosts 映射、问题清单。

### 一键（不含 serve）

```bash
python zhijing_recon.py all --ak <AK> --sk <SK> --out ./recon-out
```

## 五、红线（必须遵守）

1. **先报备**：任何在内网运行的采集动作，先跟责任民警/科信说明用途与范围。
2. **不扫描**：本工具只访问你显式给出的、或文档列出的**具体地址**，绝不做端口扫描/目录探测。
   `serve` 是**被动接收**，不主动连平台。
3. **不碰私钥**：客户端脚本只读证书的 `Subject/Issuer/有效期/指纹/HasPrivateKey`，
   **不调用任何导出接口**（`Export-Certificate`、`certutil -exportPFX` 等一律不用）。
4. **产物不出网**：回调 JSONL 含令牌、`token-*.json` 含 AK/SK 遮蔽后的报文，
   客户端报告含人员证书标识 —— 全部按敏感材料处置，**留在内网**。
5. **不替代要材料**：AK/SK、标准码、服务地址这些仍然要**正式去要**，脚本不解决。

## 六、产物清单

| 文件 | 内容 | 敏感性 |
| --- | --- | --- |
| `check-<ts>.md` / `.json` | 连通性、服务端证书链、时钟偏差 | 低 |
| `callbacks-<ts>.jsonl` | 回调原始报文（含令牌） | **高（凭据材料）** |
| `callback-report-<ts>.md` | 上述报文的汇总（默认脱敏） | 中 |
| `token-<ts>.json` | AK/SK 校验与 SM3 签名自证结果（SK 已遮蔽） | 中 |
| `auditstats-<ts>.json` | 本地审计统计 | 中 |
| `client-inventory-<ts>.json` / `.md` | 终端、证书存储、网络配置 | **高（人员证书标识）** |

## 七、已知限制

- **`getLoginUser` 被代调两次不会互相干扰吗？** `serve` 的代调是只读查询；但若平台把令牌设计成
  一次性，请**在采集窗口内只让观测器接回调**（即暂时不指向应用本身），避免应用侧开销。
  如需关掉代调：`serve --no-auth-call`。
- **`serve` 默认监听 `0.0.0.0`**：只在报备后这样用；可 `--bind 127.0.0.1` 配合 nginx 暴露单一路径。
- **`GAPM-agent` 不覆盖 Python 后端**：稳定性探针是否免接仍需智慧运维书面确认，与本工具无关。
- **本工具不判断「电子证书」本身的密码学合规性**（如 SM2 算法合规），那属于等保/国密测评范围。

## 八、与本项目其它交付物的关系

| 已有 | 用途 | 与本工具的分工 |
| --- | --- | --- |
| `docs/zhijing-integration-request.md` | 向省厅/对接人索取 5 项信息的话术 | **先发这个**，本工具不替代 |
| `GET /api/auth/zhijing/self-check`、`/api/zhijing/info` | 应用自身配置齐备性与地址可达性 | 应用部署后自检；本工具用于部署前的内网体检 |
| `GET /api/auth/zhijing/mapping-health` | 12 位机构码 → 6 位区划码落点体检 | 消费本工具 `report` §4 拿到的 `DM` 样本 |
| `scripts/zhijing-preflight.ps1` | 本机代码/构建/链路预检（10 项） | 交付前预检；本工具面向**内网环境与真实报文** |
