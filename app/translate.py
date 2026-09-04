"""翻译引擎：DeepSeek / 百度 / 腾讯云 / 阿里云，可切换。

统一接口：translate(text) 与 translate_partial(text)。
笔记 Agent 始终使用 DeepSeek（见 note_agent.py），不受此处影响。
"""
import base64
import hashlib
import hmac
import json
import random
import threading
import time
import urllib.parse
import urllib.request

from app import config

SYSTEM_PROMPT = (
    "你是研究生课堂的同声传译员。把老师的英文讲课内容翻译成地道简体中文。"
    "保留技术术语的中英文对应（如 gradient descent=梯度下降），"
    "口语化自然，不要增删原文没有的信息，不要解释术语。只输出译文。"
)
CONTEXT_SYSTEM_PROMPT = (
    "你是研究生课堂的同声传译员。把老师的英文讲课内容翻译成地道简体中文。"
    "你会收到最近几句的英中对照作为背景，用于理解指代（this/that/it 等）与话题连贯。"
    "只翻译【当前句】，不要重复、改写或翻译背景里的内容。"
    "若提示当前句或上一句可能被切窗截断：只译已有词语，不要补全没出现的后半句；"
    "若当前句是上一句的后半段，按同一句续写，不要当成新话题。"
    "保留技术术语的中英文对应（如 gradient descent=梯度下降），"
    "口语化自然，不要增删原文没有的信息，不要解释术语。只输出当前句的译文。"
)
PARTIAL_SYSTEM_PROMPT = (
    "你是课堂同传字幕引擎。对说话人的进行中语音做即时中文翻译，"
    "句子可能不完整，照实翻译当前内容，术语保留中英对照。只输出译文，不要补全。"
)

_NO_RETRY = ("401", "403", "invalid api key", "authentication",
             "invalid_api_key", "unauthorized")

_SENT_END = ".?!。？！"
_HANGING_LAST = frozenset({
    "a", "an", "the", "to", "of", "for", "and", "or", "but", "nor",
    "with", "by", "as", "at", "in", "on", "from", "into", "onto",
    "than", "this", "that", "these", "those", "our", "your", "their",
    "its", "we", "you", "they", "i", "it's", "we're",
    "is", "are", "was", "were", "be", "been", "being",
    "which", "who", "whom", "whose",
})


def en_truncated(text: str) -> bool:
    """英文是否不像一句说完（无句末标点）。切窗腰斩时常见。"""
    t = (text or "").rstrip()
    if not t or t.startswith("[ASR错误]") or t.startswith("[翻译失败]"):
        return False
    return t[-1] not in _SENT_END


def should_stitch(prev: str, curr: str) -> bool:
    """curr 是否更像 prev 被截断后的后半段，应拼在一起再翻译。"""
    prev = (prev or "").strip()
    curr = (curr or "").strip()
    if not prev or not curr or not en_truncated(prev):
        return False
    last = prev.split()[-1].lower().strip("\"'(),;:")
    if last in _HANGING_LAST:
        return True
    if curr[0].islower():
        return True
    first = curr.split()[0].lower().strip("\"'(),;:")
    return first in {"and", "or", "but", "because", "which", "that"}


def looks_cut(text: str) -> bool:
    """更像被切窗腰斩（停在冠词/介词/be 动词），而不是只是 Whisper 没打句号。"""
    if not en_truncated(text):
        return False
    last = (text or "").strip().split()[-1].lower().strip("\"'(),;:")
    return last in _HANGING_LAST


def join_en(*parts: str) -> str:
    return " ".join(p.strip() for p in parts if (p or "").strip())


def pending_truncated(previous: list) -> list:
    """previous: [(seq, en, zh), ...] 从旧到新。取出末尾尚未翻译的截断句。"""
    chain = []
    for seq, en, zh in reversed(previous or []):
        if (zh or "").strip():
            break
        if looks_cut(en):
            chain.append((seq, en))
        else:
            break
    chain.reverse()
    return chain


def parse_glossary_text(text: str) -> list[tuple[str, str]]:
    """解析「English = 中文」逐行术语表。"""
    terms, seen = [], set()
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        sep = next((c for c in ("=", "：", ":") if c in line), None)
        if not sep:
            continue
        en, zh = line.split(sep, 1)
        en, zh = en.strip(), zh.strip()
        if not en or not zh:
            continue
        key = en.lower()
        if key in seen:
            continue
        seen.add(key)
        terms.append((en, zh))
    return terms


def format_glossary_text(terms) -> str:
    return "\n".join(f"{en} = {zh}" for en, zh in (terms or []))


def glossary_prompt(terms) -> str:
    if not terms:
        return ""
    body = "\n".join(f"- {en} = {zh}" for en, zh in terms)
    return ("\n本课术语必须按下列对应翻译，不要另造译名；"
            "原文出现这些英文时译文用给定中文：\n" + body)


def asr_initial_prompt(terms, limit: int = 800) -> str:
    """把术语英文名拼成 Whisper initial_prompt，减少人名/课名听错。"""
    parts = [en for en, _ in (terms or []) if en]
    if not parts:
        return ""
    return ", ".join(parts)[:limit]


def is_retryable(err) -> bool:
    s = str(err).lower()
    return not any(m in s for m in _NO_RETRY)


def translate_with_retry(tsl, text: str, context=None, attempts: int = 3,
                         sleep=time.sleep) -> str:
    """定稿翻译：超时/网络可重试；鉴权错误立即失败。"""
    last = "unknown"
    delay = 0.5
    for i in range(max(1, attempts)):
        try:
            zh = tsl.translate(text, context=context)
            if (zh or "").strip() and not str(zh).startswith("[翻译失败]"):
                return zh.strip()
            last = zh or "empty"
        except Exception as e:  # noqa: BLE001
            last = e
            if not is_retryable(e):
                return f"[翻译失败] {e}"
        if i + 1 < attempts:
            sleep(delay)
            delay *= 2
    return f"[翻译失败] {last}"


class _GlossaryMixin:
    def set_glossary(self, terms):
        self.glossary = [
            (str(e).strip(), str(z).strip())
            for e, z in (terms or [])
            if str(e).strip() and str(z).strip()
        ]

    def _system(self, base: str) -> str:
        extra = glossary_prompt(getattr(self, "glossary", None))
        return base + extra if extra else base


def build_context_user(text: str, context) -> str:
    """把前 N 句英中对照背景拼进 user prompt（背景式：当前句单独翻译）。

    context: [(en, zh), ...] 时间从旧到新；zh 可能为空（未翻译/被跳过）。
    """
    hints = []
    if en_truncated(text):
        hints.append("注意：当前英文可能被录音切窗截断，只译已有词语，不要补全没出现的后半句。")
    if context:
        prev_en = (context[-1][0] or "").strip()
        if should_stitch(prev_en, text):
            hints.append(
                "注意：上一句背景的英文可能被截断，当前句多半是同一句的后半段。"
                "请按续写翻译，不要当成无关的新句子。")
    if not context:
        body = f"请翻译：{text}"
        return "\n".join(hints + [body]) if hints else body
    lines = list(hints)
    for i, (en, zh) in enumerate(context, 1):
        lines.append(f"背景{i}（英文）：{en}")
        if zh:
            lines.append(f"背景{i}（中文）：{zh}")
    lines.append(f"请翻译当前句：{text}")
    return "\n".join(lines)


def llm_translate_prompts(text: str, context, last_zh: str = "") -> tuple[str, str]:
    """LLM 引擎的 (system, user)。无背景时仍走 build_context_user，以便带上截断提示。"""
    if context:
        return CONTEXT_SYSTEM_PROMPT, build_context_user(text, context)
    user = build_context_user(text, None)
    if last_zh:
        user = f"上一句译文（上下文）：{last_zh}\n{user}"
    sys_p = CONTEXT_SYSTEM_PROMPT if en_truncated(text) else SYSTEM_PROMPT
    return sys_p, user


def _http_post(url, headers=None, data=None, timeout=30):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def _sse_first_chunk(url, headers, payload, budget_chars=40, budget_sec=2.0):
    """SSE 流式调用：取前 N 字或前 S 秒即断开返回。

    首段 token 远早于全句生成完；返回后关闭连接，服务端停止生成。
    """
    payload = dict(payload)
    payload["stream"] = True
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers=headers)
    t0 = time.time()
    chunks = []
    total = 0
    with urllib.request.urlopen(req, timeout=15.0) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                delta = json.loads(data)["choices"][0]["delta"].get("content", "")
            except Exception:  # noqa: BLE001
                continue
            if delta:
                chunks.append(delta)
                total += len(delta)
                if total >= budget_chars or time.time() - t0 >= budget_sec:
                    break
    return "".join(chunks).strip()


# ---------------------------------------------------------------- DeepSeek
class DeepSeekTranslator(_GlossaryMixin):
    name = "deepseek"

    def __init__(self, api_key=None, base_url=None, model=None, timeout=30.0):
        self.api_key = api_key or config.DEEPSEEK_API_KEY
        self.base_url = base_url or config.DEEPSEEK_BASE_URL
        self.model = model or config.DEEPSEEK_MODEL
        self.timeout = timeout
        self.last_zh = ""
        self.glossary = []

    def _call(self, system: str, user: str, max_tokens: int = 512) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.3,
            "stream": False,
        }
        body = _http_post(
            f"{self.base_url}/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            data=json.dumps(payload).encode("utf-8"),
            timeout=self.timeout,
        )
        return json.loads(body)["choices"][0]["message"]["content"].strip()

    def translate(self, text: str, context=None) -> str:
        """逐句翻译。context=[(en, zh), ...] 为前 N 句背景（英中对照）；
        非空时用背景 prompt 帮助指代理解，且不再叠加 last_zh（背景已含上句）。
        """
        if not text.strip():
            return ""
        sys_p, user = llm_translate_prompts(text, context, getattr(self, "last_zh", ""))
        zh = self._call(self._system(sys_p), user)
        if zh:
            self.last_zh = zh
        return zh

    def translate_partial(self, text: str) -> str:
        if not text.strip():
            return ""
        try:
            # 流式取首段：首 token 一到即上屏，不等全句生成完
            return _sse_first_chunk(
                f"{self.base_url}/chat/completions",
                {"Content-Type": "application/json",
                 "Authorization": f"Bearer {self.api_key}"},
                {"model": self.model,
                 "messages": [{"role": "system", "content": PARTIAL_SYSTEM_PROMPT},
                              {"role": "user", "content": f"请翻译：{text}"}],
                 "max_tokens": 256, "temperature": 0.3},
            )
        except Exception:  # noqa: BLE001
            return ""


# ---------------------------------------------------------------- 阿里百炼（DashScope Qwen）
class DashScopeTranslator(_GlossaryMixin):
    """阿里云百炼 DashScope：OpenAI 兼容接口 + qwen 模型（新用户有免费额度）。"""
    name = "dashscope"

    def __init__(self, api_key=None, model=None, timeout=30.0):
        self.api_key = api_key or config.DASHSCOPE_API_KEY
        self.model = model or config.DASHSCOPE_MODEL
        self.timeout = timeout
        self.last_zh = ""
        self.glossary = []

    def _call(self, system: str, user: str, max_tokens: int = 512) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.3,
            "stream": False,
        }
        body = _http_post(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            data=json.dumps(payload).encode("utf-8"),
            timeout=self.timeout,
        )
        return json.loads(body)["choices"][0]["message"]["content"].strip()

    def translate(self, text: str, context=None) -> str:
        if not text.strip():
            return ""
        sys_p, user = llm_translate_prompts(text, context, getattr(self, "last_zh", ""))
        zh = self._call(self._system(sys_p), user)
        if zh:
            self.last_zh = zh
        return zh

    def translate_partial(self, text: str) -> str:
        if not text.strip():
            return ""
        try:
            return _sse_first_chunk(
                "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                {"Content-Type": "application/json",
                 "Authorization": f"Bearer {self.api_key}"},
                {"model": self.model,
                 "messages": [{"role": "system", "content": PARTIAL_SYSTEM_PROMPT},
                              {"role": "user", "content": f"请翻译：{text}"}],
                 "max_tokens": 256, "temperature": 0.3},
            )
        except Exception:  # noqa: BLE001
            return ""


# ---------------------------------------------------------------- 百度翻译（免费）
class BaiduTranslator(_GlossaryMixin):
    """百度翻译开放平台 标准版：免费 5 万字符/月（个人认证 100 万）。QPS=1！

    实时链路拆线程后 partial 与 final 可能并发请求，而百度标准版 QPS=1，
    并发会触发 54003 限流 → 用信号量把请求串行化（同引擎同时最多 1 个在飞）。
    """
    name = "baidu"

    def __init__(self, appid=None, secret=None, timeout=15.0):
        self.appid = appid or config.BAIDU_APPID
        self.secret = secret or config.BAIDU_SECRET
        self.timeout = timeout
        self._lock = threading.Semaphore(1)
        self.glossary = []

    def _call(self, text: str) -> str:
        salt = str(random.randint(32768, 65536))
        sign = hashlib.md5(f"{self.appid}{text}{salt}{self.secret}".encode()).hexdigest()
        params = urllib.parse.urlencode({
            "q": text, "from": "en", "to": "zh",
            "appid": self.appid, "salt": salt, "sign": sign,
        })
        body = _http_post(
            "https://api.fanyi.baidu.com/api/trans/vip/translate",
            data=params.encode("utf-8"),
            timeout=self.timeout,
        )
        data = json.loads(body)
        if "trans_result" not in data:
            raise RuntimeError(f"百度翻译返回错误: {data.get('error_msg', data)}")
        return "".join(r["dst"] for r in data["trans_result"]).strip()

    def translate(self, text: str, context=None) -> str:
        """统计类引擎不支持上下文 prompt，忽略 context。"""
        if not text.strip():
            return ""
        with self._lock:
            return self._call(text)

    def translate_partial(self, text: str) -> str:
        with self._lock:
            return self.translate(text)


# ---------------------------------------------------------------- 腾讯云机器翻译
class TencentTranslator(_GlossaryMixin):
    """腾讯云 TMT TextTranslate（TC3-HMAC-SHA256 签名）。新人免费额度。"""
    name = "tencent"

    def __init__(self, secret_id=None, secret_key=None, region="ap-guangzhou", timeout=15.0):
        self.secret_id = secret_id or config.TENCENT_SECRET_ID
        self.secret_key = secret_key or config.TENCENT_SECRET_KEY
        self.region = region
        self.timeout = timeout
        self.service = "tmt"
        self.host = "tmt.tencentcloudapi.com"
        self.glossary = []

    def _sign(self, payload_json: str) -> dict:
        ts = int(time.time())
        date = time.strftime("%Y-%m-%d", time.gmtime(ts))
        # 官方 TC3 规范：CanonicalHeaders 每行 "key:value\n"，key 全小写，行间与行尾都要 \n
        canonical_headers = (
            "content-type:application/json; charset=utf-8\n"
            f"host:{self.host}\n")
        signed_headers = "content-type;host"
        payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()
        canonical_request = "\n".join(
            ["POST", "/", "", canonical_headers, signed_headers, payload_hash])
        scope = f"{date}/{self.service}/tc3_request"
        string_to_sign = "\n".join([
            "TC3-HMAC-SHA256", str(ts), scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ])
        k_date = hmac.new(f"TC3{self.secret_key}".encode(), date.encode(), hashlib.sha256).digest()
        k_service = hmac.new(k_date, self.service.encode(), hashlib.sha256).digest()
        k_signing = hmac.new(k_service, b"tc3_request", hashlib.sha256).digest()
        signature = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()
        authorization = (
            f"TC3-HMAC-SHA256 Credential={self.secret_id}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}")
        return {
            "Authorization": authorization,
            "Content-Type": "application/json; charset=utf-8",
            "Host": self.host,
            "X-TC-Action": "TextTranslate",
            "X-TC-Version": "2018-03-21",
            "X-TC-Timestamp": str(ts),
            "X-TC-Region": self.region,
        }

    def _call(self, text: str) -> str:
        payload = json.dumps(
            {"SourceText": text, "Source": "en", "Target": "zh", "ProjectId": 0})
        body = _http_post(
            f"https://{self.host}/", headers=self._sign(payload),
            data=payload.encode("utf-8"), timeout=self.timeout)
        data = json.loads(body)
        if "Response" not in data or "TargetText" not in data["Response"]:
            raise RuntimeError(f"腾讯翻译返回错误: {data}")
        return data["Response"]["TargetText"].strip()

    def translate(self, text: str, context=None) -> str:
        """统计类引擎不支持上下文 prompt，忽略 context。"""
        return self._call(text) if text.strip() else ""

    def translate_partial(self, text: str) -> str:
        return self.translate(text)


# ---------------------------------------------------------------- 阿里云机器翻译
class AlibabaTranslator(_GlossaryMixin):
    """阿里云 alimt TranslateGeneral（RPC V1 签名）。新人免费额度。"""
    name = "alibaba"

    def __init__(self, access_key_id=None, access_key_secret=None, timeout=15.0):
        self.access_key_id = access_key_id or config.ALI_ACCESS_KEY_ID
        self.access_key_secret = access_key_secret or config.ALI_ACCESS_KEY_SECRET
        self.timeout = timeout
        self.glossary = []

    def _sign_and_call(self, text: str) -> str:
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        params = {
            "Format": "JSON",
            "Version": "2018-10-12",
            "AccessKeyId": self.access_key_id,
            "SignatureMethod": "HMAC-SHA1",
            "SignatureVersion": "1.0",
            "SignatureNonce": str(random.randint(100000, 999999999)),
            "Timestamp": ts,
            "Action": "TranslateGeneral",
            "FormatType": "text",
            "SourceLanguage": "en",
            "TargetLanguage": "zh",
            "SourceText": text,
        }
        items = sorted(params.items())
        # RFC3986 编码（空格=%20 而非 +，/ 也要转义），否则签名不匹配
        qs = urllib.parse.urlencode(
            items, quote_via=lambda s, *a: urllib.parse.quote(s, safe="~"))
        string_to_sign = "POST&%2F&" + urllib.parse.quote(qs, safe="~")
        signature = urllib.parse.quote(
            base64.b64encode(
                hmac.new(f"{self.access_key_secret}&".encode(), string_to_sign.encode(),
                         hashlib.sha1).digest()).decode(), safe="~")
        data = f"{qs}&Signature={signature}".encode()
        body = _http_post("https://mt.aliyuncs.com/", data=data, timeout=self.timeout)
        result = json.loads(body)
        if "Data" not in result or "Translated" not in result["Data"]:
            raise RuntimeError(f"阿里翻译返回错误: {result}")
        return result["Data"]["Translated"].strip()

    def translate(self, text: str, context=None) -> str:
        """统计类引擎不支持上下文 prompt，忽略 context。"""
        return self._sign_and_call(text) if text.strip() else ""

    def translate_partial(self, text: str) -> str:
        return self.translate(text)


# ---------------------------------------------------------------- Ollama（本地/远程）
class OllamaTranslator(_GlossaryMixin):
    """Ollama 服务（OpenAI 兼容 /v1/chat/completions）。

    默认本机 127.0.0.1:11434；配合 Tailscale 可把 base_url 指向
    其他机器的 Ollama（如 Windows 台式机的 100.x.y.z:11434）。
    免费、断网可用；速度取决于硬件（RTX 5080 跑 14B ≈ 40-80 tok/s）。
    """

    name = "ollama"

    def __init__(self, base_url=None, model=None, timeout=90.0):
        self.base_url = (base_url or config.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or config.OLLAMA_MODEL
        self.timeout = timeout
        self.last_zh = ""
        self.glossary = []

    def _call(self, system: str, user: str, max_tokens: int = 512) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.3,
            "stream": False,
        }
        body = _http_post(
            f"{self.base_url}/chat/completions",
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload).encode("utf-8"),
            timeout=self.timeout,
        )
        return json.loads(body)["choices"][0]["message"]["content"].strip()

    def translate(self, text: str, context=None) -> str:
        if not text.strip():
            return ""
        sys_p, user = llm_translate_prompts(text, context, getattr(self, "last_zh", ""))
        zh = self._call(self._system(sys_p), user)
        if zh:
            self.last_zh = zh
        return zh

    def translate_partial(self, text: str) -> str:
        if not text.strip():
            return ""
        try:
            return _sse_first_chunk(
                f"{self.base_url}/chat/completions",
                {"Content-Type": "application/json"},
                {"model": self.model,
                 "messages": [{"role": "system", "content": PARTIAL_SYSTEM_PROMPT},
                              {"role": "user", "content": f"请翻译：{text}"}],
                 "max_tokens": 256, "temperature": 0.3},
            )
        except Exception:  # noqa: BLE001
            return ""


# ---------------------------------------------------------------- 工厂
def _cred(val: str) -> bool:
    """占位符（your- / sk-your-）不算已配置。"""
    v = (val or "").strip()
    if not v:
        return False
    low = v.lower()
    return not (low.startswith("your-") or low.startswith("sk-your-"))


def provider_ready(provider: str) -> bool:
    p = (provider or "").strip().lower()
    if p == "deepseek":
        return _cred(config.DEEPSEEK_API_KEY)
    if p == "dashscope":
        return _cred(config.DASHSCOPE_API_KEY)
    if p == "baidu":
        return _cred(config.BAIDU_APPID) and _cred(config.BAIDU_SECRET)
    if p == "tencent":
        return _cred(config.TENCENT_SECRET_ID) and _cred(config.TENCENT_SECRET_KEY)
    if p == "alibaba":
        return _cred(config.ALI_ACCESS_KEY_ID) and _cred(config.ALI_ACCESS_KEY_SECRET)
    if p == "ollama":
        return True
    return False


def llm_ready() -> bool:
    """课后笔记、术语提取走 DeepSeek，与课堂翻译引擎无关。"""
    return provider_ready("deepseek")


def resolve_provider(preferred: str | None = None) -> str | None:
    """课堂翻译引擎：设置优先；该引擎没 Key 则落到已填写的机器翻译。不自动选 Ollama。"""
    pref = (preferred or config.TRANSLATE_PROVIDER or "deepseek").strip().lower()
    if provider_ready(pref):
        return pref
    for p in ("tencent", "baidu", "alibaba", "dashscope", "deepseek"):
        if p != pref and provider_ready(p):
            return p
    return None


def make_translator(provider: str | None = None):
    provider = provider or resolve_provider() or config.TRANSLATE_PROVIDER
    if provider == "baidu":
        return BaiduTranslator()
    if provider == "tencent":
        return TencentTranslator()
    if provider == "alibaba":
        return AlibabaTranslator()
    if provider == "dashscope":
        return DashScopeTranslator()
    if provider == "ollama":
        return OllamaTranslator()
    return DeepSeekTranslator()
