import re
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


class IntentDetector:
    """
    Lightweight keyword-based intent detection that runs BEFORE the main LLM call.
    Used to pre-classify user messages and route to appropriate tools or flows,
    reducing LLM latency for common patterns.
    """

    INTENTS: dict[str, list[str]] = {
        "order_food": [
            "order", "pizza", "burger", "sandwich", "pasta", "wings",
            "food", "delivery", "meal", "eat", "hungry", "menu",
            "i want", "i'd like", "can i get", "give me",
        ],
        "book_appointment": [
            "appointment", "book", "schedule", "slot", "reserve",
            "session", "consultation", "meeting", "visit",
            "when can i", "available", "earliest",
        ],
        "cancel": [
            "cancel", "cancell", "stop", "remove", "delete", "no longer",
            "don't want", "nevermind", "forget it", "abort",
        ],
        "status_check": [
            "status", "where", "track", "order status", "how long",
            "when will", "eta", "estimated", "update", "progress",
        ],
        "pricing": [
            "how much", "price", "cost", "fee", "charge", "rate",
            "expensive", "cheap", "affordable", "pricing", "quote",
            "what's the", "total", "bill",
        ],
        "hours": [
            "open", "hours", "close", "closing", "when", "schedule",
            "business hours", "operating hours", "what time", "until",
            "available hours",
        ],
        "escalate": [
            "human", "agent", "speak to", "talk to person", "real person",
            "supervisor", "manager", "customer service", "representative",
            "transfer", "connect me", "live agent",
        ],
        "greeting": [
            "hi", "hello", "hey", "good morning", "good afternoon",
            "good evening", "howdy", "what's up", "greetings", "hiya",
        ],
        "farewell": [
            "bye", "goodbye", "good bye", "thanks", "thank you",
            "see you", "take care", "have a good", "that's all",
            "no more", "done", "finished",
        ],
        "complaint": [
            "unhappy", "disappointed", "terrible", "awful", "bad",
            "wrong", "incorrect", "mistake", "problem", "issue",
            "broken", "not working", "failed", "late", "never arrived",
        ],
        "payment": [
            "pay", "payment", "card", "credit", "debit", "cash",
            "invoice", "receipt", "refund", "charge", "billing",
        ],
        "location": [
            "where are you", "address", "location", "directions",
            "how to get", "near me", "closest", "find you", "map",
        ],
    }

    # Entity extraction patterns per intent
    ENTITY_PATTERNS: dict[str, dict[str, str]] = {
        "order_food": {
            "quantity": r"\b(\d+)\b",
            "size": r"\b(small|medium|large|xl|extra large|regular)\b",
            "item": r"\b(pizza|burger|sandwich|pasta|wings|salad|soup|fries|drink|soda|water)\b",
        },
        "book_appointment": {
            "date": r"\b(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\b",
            "time": r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)?)\b",
            "service": r"\b(haircut|massage|facial|manicure|pedicure|checkup|consultation|cleaning)\b",
        },
        "status_check": {
            "order_id": r"\b([A-Z]{2,}\d{4,}|#\d{4,}|\d{6,})\b",
        },
        "pricing": {
            "item": r"\b(pizza|burger|sandwich|pasta|wings|haircut|massage|consultation|cleaning)\b",
        },
    }

    def detect_intent(self, text: str) -> str:
        """
        Classify a user message into one of the known intent categories.
        Uses case-insensitive keyword matching. Returns 'unknown' if no match.
        Falls back to the highest-scoring intent if multiple match.
        """
        if not text or not text.strip():
            return "unknown"

        normalized = text.lower().strip()
        scores: dict[str, int] = {}

        for intent, keywords in self.INTENTS.items():
            score = 0
            for keyword in keywords:
                # Use word-boundary aware matching for multi-word keywords
                if " " in keyword:
                    if keyword in normalized:
                        score += 2  # Multi-word keywords are more specific
                else:
                    pattern = r"\b" + re.escape(keyword) + r"\b"
                    if re.search(pattern, normalized):
                        score += 1
            if score > 0:
                scores[intent] = score

        if not scores:
            return "unknown"

        # Return the highest-scoring intent
        best_intent = max(scores, key=lambda k: scores[k])
        logger.debug(
            "intent_detected",
            text=text[:100],
            intent=best_intent,
            score=scores[best_intent],
        )
        return best_intent

    def detect_all_intents(self, text: str) -> list[tuple[str, int]]:
        """
        Returns all matching intents sorted by score descending.
        Useful for multi-intent messages.
        """
        if not text or not text.strip():
            return []

        normalized = text.lower().strip()
        scores: dict[str, int] = {}

        for intent, keywords in self.INTENTS.items():
            score = 0
            for keyword in keywords:
                if " " in keyword:
                    if keyword in normalized:
                        score += 2
                else:
                    pattern = r"\b" + re.escape(keyword) + r"\b"
                    if re.search(pattern, normalized):
                        score += 1
            if score > 0:
                scores[intent] = score

        return sorted(scores.items(), key=lambda x: x[1], reverse=True)

    def extract_entities(self, text: str, intent: str) -> dict:
        """
        Extract named entities from the text for a known intent.
        Returns a dict of entity_name -> extracted value (or list of values).
        """
        entities: dict[str, object] = {}
        patterns = self.ENTITY_PATTERNS.get(intent, {})

        if not patterns:
            return entities

        normalized = text.lower()
        for entity_name, pattern in patterns.items():
            matches = re.findall(pattern, normalized, re.IGNORECASE)
            if matches:
                # Return single value for single match, list for multiple
                entities[entity_name] = matches[0] if len(matches) == 1 else matches

        return entities

    def should_escalate_immediately(self, text: str) -> bool:
        """
        Quick check: does the user explicitly want a human right now?
        """
        escalation_phrases = [
            "speak to a human", "talk to a person", "talk to an agent",
            "real person", "live agent", "human agent", "customer service",
            "speak to someone", "connect me to a human",
        ]
        normalized = text.lower()
        for phrase in escalation_phrases:
            if phrase in normalized:
                return True
        return self.detect_intent(text) == "escalate"

    def is_greeting(self, text: str) -> bool:
        """Check if message is a simple greeting."""
        return self.detect_intent(text) == "greeting"

    def is_farewell(self, text: str) -> bool:
        """Check if message is a farewell."""
        return self.detect_intent(text) == "farewell"

    def detect_language(self, text: str, supported_langs: list[str]) -> Optional[str]:
        """
        Heuristic-based language detection for common patterns.
        Falls back to None if unsure.
        """
        if not text: return None
        t = text.lower().strip()
        
        # French patterns
        fr_patterns = [
            r"\bbonjour\b", r"\bsalut\b", r"\bpouvez-vous\b", r"\baidez-moi\b",
            r"\bcomment\b", r"\bmerci\b", r"\boui\b", r"\bnon\b", r"\bfrançais\b",
        ]
        
        if any(re.search(p, t) for p in fr_patterns):
            # Resolve to the specific supported code if possible (e.g. fr-CA or fr)
            if "fr-CA" in supported_langs: return "fr-CA"
            if "fr" in supported_langs: return "fr"
            return "fr"

        # English patterns
        en_patterns = [
            r"\bhello\b", r"\bhi\b", r"\bcan you\b", r"\bhelp\b", r"\bhow\b",
            r"\bthanks\b", r"\byes\b", r"\bno\b", r"\benglish\b",
        ]
        if any(re.search(p, t) for p in en_patterns):
            if "en-US" in supported_langs: return "en-US"
            if "en" in supported_langs: return "en"
            return "en"
            
        return None
