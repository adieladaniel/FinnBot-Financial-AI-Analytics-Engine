import re

from rapidfuzz import fuzz

from core.vocabulary import normalize_text, split_schema_name

TOKEN_RE = re.compile(r"[a-zA-Z']+")

MIN_TOKEN_LEN = 4
MATCH_THRESHOLD = 80
LENGTH_WINDOW = 2

STRUCTURAL_KEYWORDS = {
    "count", "how", "many", "number", "of", "what", "is", "tell", "give", "me",
    "top", "bottom", "highest", "lowest", "least", "most", "largest", "smallest",
    "list", "show", "rows", "records", "details",
    "compare", "comparison", "versus", "against", "and",
    "average", "avg", "mean", "max", "maximum", "min", "minimum",
    "greater", "than", "more", "above", "over", "less", "below", "under",
    "at", "exactly", "zero", "no",
    "his", "her", "their", "there", "those", "these", "them",
    "student", "students", "all", "three", "five",
    "group", "category", "segment", "type",
    "any", "overall", "dataset", "table", "across",
    "now", "about", "this", "that", "one",
    "today", "yesterday", "month", "year", "date", "collection", "received",
    "paid", "payment", "payments", "balance", "outstanding", "pending", "due",
    "concession", "discount", "waiver", "payable", "fees", "fee", "amount",
}


def build_correction_vocabulary(schema: dict, measures: dict, domain_config: dict) -> set:
    vocab = set(STRUCTURAL_KEYWORDS)

    for m_def in measures.values():
        for alias in m_def.get("aliases", []):
            vocab.update(normalize_text(alias).split())

    for phrase in domain_config.get("semantic_aliases", {}).keys():
        vocab.update(normalize_text(phrase).split())

    for word in domain_config.get("context_measure_words", {}).keys():
        vocab.add(normalize_text(word))

    for phrases in domain_config.get("zero_value_phrases", {}).values():
        for phrase in phrases:
            vocab.update(normalize_text(phrase).split())

    for phrase in domain_config.get("semantic_phrases_for_fallback", []):
        vocab.update(normalize_text(phrase).split())

    for col in schema.get("dimensions", []):
        vocab.update(normalize_text(col).split())
        for form in split_schema_name(col):
            vocab.update(form.split())

    vocab.discard("")
    return vocab


def correct_query_typos(question: str, vocabulary: set, threshold: int = MATCH_THRESHOLD) -> str:
    vocab_by_len = {}
    for word in vocabulary:
        vocab_by_len.setdefault(len(word), []).append(word)

    def correct_token(match: re.Match) -> str:
        token = match.group(0)
        lower = token.lower()

        if lower in vocabulary or len(lower) < MIN_TOKEN_LEN:
            return token

        best_word = None
        best_score = 0.0

        for length in range(len(lower) - LENGTH_WINDOW, len(lower) + LENGTH_WINDOW + 1):
            for candidate in vocab_by_len.get(length, []):
                score = fuzz.ratio(lower, candidate)
                if score > best_score:
                    best_score = score
                    best_word = candidate

        if best_word and best_score >= threshold:
            return best_word

        return token

    return TOKEN_RE.sub(correct_token, question)
