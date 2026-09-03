"""全局配置：从 .env / 环境变量读取，统一收敛常量。"""
import os
import pathlib

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent


def load_dotenv(path: pathlib.Path = BASE_DIR / ".env"):
    """极简 .env 解析（不引第三方依赖），不覆盖已有环境变量。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


load_dotenv()

# ---- DeepSeek ----
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

# ---- 翻译引擎（deepseek / baidu / tencent / alibaba / dashscope / ollama）----
TRANSLATE_PROVIDER = os.environ.get("TRANSLATE_PROVIDER", "deepseek")
BAIDU_APPID = os.environ.get("BAIDU_APPID", "")
BAIDU_SECRET = os.environ.get("BAIDU_SECRET", "")
TENCENT_SECRET_ID = os.environ.get("TENCENT_SECRET_ID", "")
TENCENT_SECRET_KEY = os.environ.get("TENCENT_SECRET_KEY", "")
ALI_ACCESS_KEY_ID = os.environ.get("ALI_ACCESS_KEY_ID", "")
ALI_ACCESS_KEY_SECRET = os.environ.get("ALI_ACCESS_KEY_SECRET", "")
DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
DASHSCOPE_MODEL = os.environ.get("DASHSCOPE_MODEL", "qwen-turbo")

# 本地/远程 Ollama（OpenAI 兼容）：默认本机；配 Tailscale 可指向 Windows 机器 IP
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b-instruct")

# ---- 翻译 ----
# 逐句翻译带前 N 句背景（背景式上下文：当前句单独翻译，前 N 句英中对照注入
# prompt 供指代/话题理解，维持逐句 1:1 对齐）。0=关闭（与旧版一致）。
TRANSLATE_CONTEXT = int(os.environ.get("TRANSLATE_CONTEXT", "2"))

# ---- ASR ----
ASR_MODEL = os.environ.get("ASR_MODEL", "small")   # tiny/base/small/medium/large
ASR_PARTIAL_MODEL = os.environ.get("ASR_PARTIAL_MODEL", "small")  # 字幕草稿（轻量跟读；定稿用 ASR_MODEL）
ASR_LANGUAGE = os.environ.get("ASR_LANGUAGE", "en")
ASR_BEAM = 5

# ---- 采集与分块 ----
SAMPLE_RATE = 16000
BLOCK_SEC = 0.1            # 采集块时长
VAD_THRESHOLD = 0.5        # silero 语音概率阈值
SILENCE_TAIL_SEC = 0.6     # 判定句子结束的静音尾巴
CHUNK_MAX_SEC = 10.0       # 单个切块上限（超长强制截断）

# ---- 存储 ----
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "subtitle.db"
EXPORT_DIR = DATA_DIR / "exports"
AUDIO_DIR = DATA_DIR / "audio"
MATERIALS_DIR = DATA_DIR / "materials"
