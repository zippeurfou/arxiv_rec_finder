from collections.abc import Callable
from dataclasses import dataclass
import json
import re

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


@dataclass
class Extraction:
    concepts_raw: list[str]
    technical_note: str


PROMPT = """You are indexing a recommendation-systems paper for a technical knowledge base.
Read the paper and return STRICT JSON with keys:
- "concepts_raw": a generous, recall-biased list of the techniques/ideas the paper ACTUALLY
  discusses (short noun phrases). Include secondary techniques. Prefer these canonical phrasings
  where they apply: {vocab_hint}. Do NOT invent concepts not in the paper.
- "technical_note": 3-5 sentences: problem, method, key result. No preamble.

TITLE: {title}

PAPER:
{fulltext}
"""


def extract_paper(
    title: str, fulltext: str, vocab_hint: list[str], llm: Callable[[str], str]
) -> Extraction:
    raw = llm(
        PROMPT.format(
            title=title, fulltext=fulltext[:60000], vocab_hint=", ".join(vocab_hint)
        )
    )
    # Reasoning models (e.g. deepseek-r1) emit <think>...</think> that often
    # contains braces; strip it before slicing so the JSON parse is reliable.
    raw = _THINK.sub("", raw)
    data = json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
    return Extraction(
        concepts_raw=[c.strip() for c in data["concepts_raw"] if c.strip()],
        technical_note=data["technical_note"].strip(),
    )


def ollama_llm(model: str = "deepseek-r1:latest"):
    from ollama import Client

    client = Client()

    def _call(prompt: str) -> str:
        return client.chat(model=model, messages=[{"role": "user", "content": prompt}])[
            "message"
        ]["content"]

    return _call
