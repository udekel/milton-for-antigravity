import re
from typing import Any, Dict, List, Union


class PIIRedactor:
    """PII & Credentials Redactor.
    
    Detects and masks emails, API keys/tokens, private keys, IPv4/IPv6 addresses,
    and sensitive dictionary keys (passwords, secrets, credentials).
    """

    EMAIL_REGEX = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')
    API_KEY_PATTERNS = [
        re.compile(r'(?:token|api[_-]?key|secret|pat)[_-]?[a-zA-Z0-9_]{16,}', re.IGNORECASE),
        re.compile(r'(?:bearer|token|api[_-]?key|secret)\s*[:=]\s*["\']?([a-zA-Z0-9_\-\.]{16,})["\']?', re.IGNORECASE),
        re.compile(r'-----BEGIN (RSA|OPENSSH|EC|PGP|PRIVATE) KEY-----[\s\S]+?-----END \1 KEY-----'),
    ]


    IP_REGEX = re.compile(r'\b(?!127\.0\.0\.1\b)(?!0\.0\.0\.0\b)(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b')
    SENSITIVE_KEYS = {"password", "passwd", "secret", "token", "access_token", "api_key", "authorization", "auth"}

    @classmethod
    def redact_text(cls, text: str) -> str:
        if not text or not isinstance(text, str):
            return text

        # Redact emails
        redacted = cls.EMAIL_REGEX.sub("[REDACTED_EMAIL]", text)

        # Redact API keys and private keys
        for pattern in cls.API_KEY_PATTERNS:
            redacted = pattern.sub("[REDACTED_SECRET]", redacted)

        # Redact IP addresses
        redacted = cls.IP_REGEX.sub("[REDACTED_IP]", redacted)

        return redacted

    @classmethod
    def redact_data(cls, data: Union[Dict[str, Any], List[Any], str, Any]) -> Any:
        if isinstance(data, str):
            return cls.redact_text(data)

        if isinstance(data, dict):
            new_dict = {}
            for k, v in data.items():
                if isinstance(k, str) and k.lower() in cls.SENSITIVE_KEYS:
                    new_dict[k] = "[REDACTED_SECRET]"
                else:
                    new_dict[k] = cls.redact_data(v)
            return new_dict

        if isinstance(data, list):
            return [cls.redact_data(item) for item in data]

        return data
