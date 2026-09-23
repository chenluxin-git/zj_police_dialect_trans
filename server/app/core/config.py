"""
配置管理模块
pydantic-settings 从环境变量与 .env 文件读取配置，提供全局访问的 settings 对象
（移植自 audio-server-test/app/core/config.py：MySQL 分项配置改为单一 DATABASE_URL，
 JWT 配置改为 SECRET_KEY/ACCESS_TOKEN_EXPIRE_HOURS，新增 ASR 质检与 CORS 配置项）
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置类，所有配置项定义在此（字段名小写，环境变量大小写不敏感匹配）"""

    # ---------- 数据库配置 ----------
    database_url: str = "sqlite:///./data/app.db"

    # ---------- 文件存储配置 ----------
    audio_storage_path: str = "./audio_storage"
    export_path: str = "./data/exports"

    # ---------- JWT 配置 ----------
    secret_key: str = "change-me-in-prod"
    access_token_expire_hours: int = 12

    # ---------- CORS 配置（逗号分隔白名单） ----------
    cors_origins: str = "http://localhost:5173"

    # ---------- ASR 方言转译配置（asr_upstream_base 为空 = 质检停用） ----------
    # 契约对齐 new_tailect：POST {base}/asr?diarization=false，multipart 字段 file，响应 {"text"}
    asr_upstream_base: str = "https://1plxo01525881.vicp.fun"
    asr_timeout: int = 300
    asr_verify_ssl: bool = False  # 上游为内网穿透自签证书，默认不校验

    # ---------- 质检配置 ----------
    qc_similarity_threshold: float = 0.5
    qc_max_retry: int = 3
    qc_scan_interval: int = 60

    # ---------- 导入/扫盘运行目录（容器内指向 /data 卷，防侧车台账落容器临时层） ----------
    text_import_dir: str = "data/text_imports"
    audio_import_dir: str = "data/audio_imports"
    scan_root: str = ""   # 扫盘白名单根目录；空=不限制（仅限本机开发），生产/容器必设

    # ================= 浙警智治接入配置（用户域 + 省厅零信任） =================
    # ---------- 应用身份（资源管理器/上架时获取） ----------
    zhijing_sys_id: str = ""            # 系统标准码 / requestId：数据编目、智慧运维、审计三处共用
    zhijing_app_key: str = ""           # 应用主键 AK
    zhijing_app_secret: str = ""        # 密钥主键 SK / 审计 appSecret（两者取同一注册密钥）
    zhijing_dqxtbs: str = ""            # 当前系统标识（不填时可回退 sys_id）
    zhijing_auth_button: str = ""       # 应用标识 APPID（应用级鉴权用；空=不传）

    # ---------- 服务地址（用户域省厅地址；地市应用由本地科信另给） ----------
    zhijing_rz_url: str = "https://lxrdl.gat.zj:5010/jiRMS_RzSer"    # 认证服务 SerRzIP
    zhijing_qx_url: str = "https://lxrdl.gat.zj:5020/jiRMS_QxSer"    # 权限服务 SerQxIP
    zhijing_audit_url: str = "https://41.188.255.179:9000"           # 审计服务 SJSerIP
    zhijing_verify_ssl: bool = False    # 内网自签/私有 CA，默认不校验
    zhijing_timeout: int = 15           # 单次调用超时（秒）

    # ---------- 接口路径（集中于此便于联调期按组件调用文档调整，勿散落到业务代码） ----------
    zhijing_path_get_login_user: str = "/jyglb/apis/V2/getLoginUser"              # 用户基本信息获取（复合）
    zhijing_path_create_app_token: str = "/jwt/nologin/V2/202307/createAppToken"  # 应用令牌生成
    zhijing_path_renew_token: str = "/jwt/nologin/V2/renewOrOfflineToken"         # 令牌续期注销（SM3 签名）
    zhijing_path_app_permission: str = "/dzRole/V2/202307/jqfw/yyj"               # 应用级鉴权
    zhijing_path_audit_json: str = "/commonApi/logApi_v2/transferJsonLog"         # 审计 JSON 上报

    # ---------- 对接模式开关 ----------
    zhijing_mode: str = "off"           # off=纯本地账号；mock=本地模拟身份（联调用）；live=真机对接
    # 身份来源：dynamic=统一认证动态秘钥回调参数（用户域标准做法）；rzzx=零信任令牌 Header；
    #          both=先令牌 Header 再回退动态秘钥参数（两者都支持的稳妥配置）
    zhijing_login_source: str = "both"
    zhijing_legacy_login: bool = True   # 过渡期保留手机号+密码登录（上架前应置 false）
    zhijing_callback_path: str = "/api/auth/zhijing/callback"   # 上架时填报的认证回调地址
    zhijing_itrust_login_url: str = "https://lxrdl.gat.zj:5010/jiRMS_RzSer"  # 令牌方式未带令牌时的跳转入口
    zhijing_pending_token_minutes: int = 10   # 动态秘钥模式下一次性 ticket 有效期（分钟）
    frontend_base: str = "/"                  # 前端基地址（子路径部署如 /record/ 时必填，用于回调 302 跳转）

    # ---------- 审计服务 ----------
    zhijing_audit_enabled: bool = False  # 审计上报总开关（live 模式必须打开）
    zhijing_audit_flush_seconds: int = 30   # 后台批量上报间隔
    zhijing_audit_retry_seconds: int = 60   # 失败重推间隔（P1：必须本地缓存后重推）
    zhijing_audit_queue_enabled: bool = True  # 是否把日志写入本地台账（测试可关闭）
    zhijing_audit_batch: int = 100          # 单批条数上限（规范 ≤100）
    zhijing_audit_max_bytes: int = 1024 * 1024  # 单批报文上限（规范 ≤1M）

    # ---------- 组织与用户同步（统一用户组件） ----------
    zhijing_org_sync_enabled: bool = False  # 部门/警员同步开关
    zhijing_org_sync_seconds: int = 60      # 定时增量频率（规范不少于 1 分钟）
    zhijing_user_default_role: str = "user" # 同步进来的警员默认角色
    zhijing_admin_police_numbers: str = ""  # 逗号分隔：这些警号同步为 admin（空=不自动授权）
    # 统一用户组件的服务基地址与接口路径（申请组件后按"组件调用文档"填写；空=不同步）
    zhijing_org_base_url: str = ""
    zhijing_org_init_path: str = "/init"                       # 信息初始化（SJLX=1 部门 / 3 用户）
    zhijing_org_dept_increment_path: str = "/deptIncrement"    # 获取部门增量信息
    zhijing_org_user_increment_path: str = "/userIncrement"    # 获取警员增量信息
    zhijing_org_page_size_dept: int = 1000  # 部门分页（规范建议 ≤1000）
    zhijing_org_page_size_user: int = 100   # 警员分页（规范建议 ≤100）
    zhijing_org_headers: str = ""           # 额外请求头，JSON 对象字符串（如 {"X-App":"zjpdt"}）

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# 创建全局配置实例，供其他模块导入使用
settings = Settings()
