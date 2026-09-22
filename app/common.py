import hashlib

LABELS = ['billing', 'account', 'technical']
# Hand-labelled synthetic fixtures; not a real-world benchmark.
TICKETS = [
    ('I need a refund', 'billing'), ('My payment failed', 'billing'),
    ('Please explain this invoice', 'billing'), ('I was charged twice', 'billing'),
    ('Reset my password', 'account'), ('I cannot login', 'account'),
    ('Change my email address', 'account'), ('My profile is locked', 'account'),
    ('The app crashes', 'technical'), ('There is an error on startup', 'technical'),
    ('The screen stays blank', 'technical'), ('Uploads stop halfway', 'technical'),
]

def draw(seed, request_id, attempt, stream):
    key = f'{seed}:{request_id}:{attempt}:{stream}'.encode()
    return int.from_bytes(hashlib.sha256(key).digest()[:8], 'big') / 2**64

def fallback(text):
    text = text.lower()
    for label, words in [('billing', ['refund', 'payment']),
                         ('account', ['password', 'login']),
                         ('technical', ['crash', 'error'])]:
        if any(word in text for word in words):
            return label
    return 'human_review'
