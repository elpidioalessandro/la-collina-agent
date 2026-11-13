import hashlib

import numpy as np
from chromadb.api.types import EmbeddingFunction


class EmbeddingFinto(EmbeddingFunction):
    """Embedding deterministico per i test: non scarica modelli, non usa la rete."""

    def __init__(self):
        pass

    def __call__(self, input):
        out = []
        for testo in input:
            v = np.zeros(64)
            for parola in testo.lower().split():
                v[int(hashlib.md5(parola[:5].encode()).hexdigest(), 16) % 64] += 1
            out.append((v / (np.linalg.norm(v) or 1)).tolist())
        return out

    @staticmethod
    def name():
        return "finto"

    def get_config(self):
        return {}

    @staticmethod
    def build_from_config(config):
        return EmbeddingFinto()


from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage


class LLMFinto(GenericFakeChatModel):
    """LLM finto che restituisce in ordine i messaggi preparati, comprese le chiamate agli strumenti."""

    def bind_tools(self, tools, **kwargs):
        return self


def llm_con_copione(*messaggi):
    return LLMFinto(messages=iter(list(messaggi)))


def chiamata(nome, argomenti, id_="c1"):
    return AIMessage(content="", tool_calls=[{"name": nome, "args": argomenti, "id": id_, "type": "tool_call"}])
