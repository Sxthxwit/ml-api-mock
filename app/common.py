import hashlib

LABELS = ["billing", "account", "technical"]
TICKETS = [
    ("I need a refund", "billing"), ("My payment failed", "billing"),
    ("Please explain this invoice", "billing"), ("I was charged twice", "billing"),
    ("Reset my password", "account"), ("I cannot login", "account"),
    ("Change my email address", "account"), ("My profile is locked", "account"),
    ("The app crashes", "technical"), ("There is an error on startup", "technical"),
    ("The screen stays blank", "technical"), ("Uploads stop halfway", "technical"),
]

def draw(seed, request_id, attempt, stream):
    """สร้างเลข 0–1 แบบทำซ้ำได้ด้วย seed/request/attempt เดียวกัน."""
    key = f"{seed}:{request_id}:{attempt}:{stream}".encode()
    return int.from_bytes(hashlib.sha256(key).digest()[:8], "big") / 2**64

# จงใจไม่ครอบคลุมทุกข้อความ เพื่อให้การทดลองวัด trade-off ของ fallback ได้จริง
# เช่น invoice และ blank screen ต้องส่งต่อให้เจ้าหน้าที่ แทนการเดาคำตอบ
SECONDARY_RULES = {"email": "account", "upload": "technical"}
LOCAL_MODEL_RULES = {"charged": "billing", "profile": "account"}
EXACT_CACHE = {"i need a refund": "billing", "i cannot login": "account"}
SEMANTIC_CACHE = {
    "refund payment": "billing", "password login": "account",
    "crash error startup": "technical",
}
RULE_BASED = {"payment": "billing", "password": "account", "crash": "technical", "error": "technical"}

def _keyword_lookup(text, rules):
    lowered = text.lower()
    return next((label for word, label in rules.items() if word in lowered), None)

def _semantic_cache_lookup(text, threshold=0.34):
    words = set(text.lower().split())
    best_label, best_score = None, 0.0
    for example, label in SEMANTIC_CACHE.items():
        cached_words = set(example.split())
        score = len(words & cached_words) / len(words | cached_words)
        if score > best_score:
            best_label, best_score = label, score
    return best_label if best_score >= threshold else None

def fallback_hierarchy(text):
    """Secondary (จำลอง) → local → cache → semantic cache → rules → human."""
    for tier, lookup in [
        ("secondary_provider", lambda: _keyword_lookup(text, SECONDARY_RULES)),
        ("small_local_model", lambda: _keyword_lookup(text, LOCAL_MODEL_RULES)),
        ("cache", lambda: EXACT_CACHE.get(text.lower())),
        ("semantic_cache", lambda: _semantic_cache_lookup(text)),
        ("rule_based", lambda: _keyword_lookup(text, RULE_BASED)),
    ]:
        label = lookup()
        if label:
            return label, tier
    return "human_review", "human_review"

def fallback(text):
    return fallback_hierarchy(text)[0]
