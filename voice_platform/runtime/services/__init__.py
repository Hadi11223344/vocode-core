"""Runtime services — ExtractionService, LLMGenerationService, KnowledgeService, MemoryService.

Uses lazy __getattr__ to avoid circular imports. The eager import chain
extraction → llm → factory → runtime.session.__init__ → builder → services.knowledge
→ services.__init__ → extraction creates a cycle. By deferring imports until
first attribute access, each module loads independently.
"""

__all__ = [
    "ExtractionPrompts",
    "ExtractionService",
    "LLMGenerationService",
    "KnowledgeContext",
    "KnowledgeDocument",
    "KnowledgeService",
    "CallSummary",
    "ConversationMemory",
    "MemoryService",
]

_LAZY_MAP = {
    "ExtractionPrompts": "voice_platform.runtime.services.extraction",
    "ExtractionService": "voice_platform.runtime.services.extraction",
    "LLMGenerationService": "voice_platform.runtime.services.llm",
    "KnowledgeContext": "voice_platform.runtime.services.knowledge",
    "KnowledgeDocument": "voice_platform.runtime.services.knowledge",
    "KnowledgeService": "voice_platform.runtime.services.knowledge",
    "CallSummary": "voice_platform.runtime.services.memory",
    "ConversationMemory": "voice_platform.runtime.services.memory",
    "MemoryService": "voice_platform.runtime.services.memory",
}


def __getattr__(name: str):
    if name in _LAZY_MAP:
        import importlib

        module = importlib.import_module(_LAZY_MAP[name])
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
