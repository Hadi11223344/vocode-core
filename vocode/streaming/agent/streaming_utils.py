import json
import re
from typing import AsyncGenerator, AsyncIterable, List, Literal, Optional, Union

from sentry_sdk.tracing import Span

from vocode.streaming.models.actions import FunctionCall, FunctionFragment

TOKENS_TO_GENERATE_PAST_PERIOD = 1
SENTENCE_ENDINGS_EXCEPT_PERIOD_PATTERN = r"[?!\n\t\r]"


# Pattern for text-based tool calls that some models emit (e.g. Llama-3.3):
#   <function=read_sheet>{"range": "A:B", "max_rows": 10}</function>
_TEXT_TOOL_CALL_PATTERN = re.compile(
    r"<function=([a-zA-Z_][a-zA-Z0-9_]*)>(\{.*?\})</function>",
    re.DOTALL,
)


def extract_text_tool_calls(text: str) -> List[tuple]:
    """Find and extract text-based <function=name>{...}</function> calls from text.

    Returns a list of (name, arguments_json, start, end) tuples.
    """
    matches = []
    for m in _TEXT_TOOL_CALL_PATTERN.finditer(text):
        matches.append((m.group(1), m.group(2), m.start(), m.end()))
    return matches


SHORT_SENTENCE_CUTOFF = 2


def split_sentences(text: str) -> List[str]:
    """Splits text into sentences and preserve trailing periods.

    Merge sentences that are just numbers, as they are part of lists.
    """
    initial_split = text.split(". ")

    final_split = []
    buffer = ""

    for i, sentence in enumerate(initial_split):
        is_last = i == len(initial_split) - 1
        buffer += sentence
        if not is_last:
            buffer += ". "
        if not re.fullmatch(r"\d+", sentence.strip()):
            final_split.append(buffer.strip())
            buffer = ""

    if buffer.strip():
        final_split.append(buffer.strip())

    return [sentence for sentence in final_split if sentence]


async def collate_response_async(
    conversation_id: str,
    gen: AsyncIterable[Union[str, FunctionFragment]],
    get_functions: Literal[True, False] = False,
    sentry_span: Optional[Span] = None,
) -> AsyncGenerator[
    Union[str, FunctionCall],
    None,
]:  # tuple of message to send and whether it's the final message
    buffer = ""
    function_name_buffer = ""
    function_args_buffer = ""
    is_post_period = False
    tokens_since_period = 0
    is_first = True
    async for token in gen:
        if is_first:
            if sentry_span:
                sentry_span.finish()
            is_first = False
        if not token:
            continue
        if isinstance(token, str):
            buffer += token
            if len(buffer.strip().split()) < SHORT_SENTENCE_CUTOFF:
                continue
            if re.search(SENTENCE_ENDINGS_EXCEPT_PERIOD_PATTERN, token):
                # split on last occurrence of sentence ending
                matches = [
                    match for match in re.finditer(SENTENCE_ENDINGS_EXCEPT_PERIOD_PATTERN, buffer)
                ]
                last_match = matches[-1]
                split_point = last_match.start() + 1
                to_keep, to_return = buffer[split_point:], buffer[:split_point]
                if to_return.strip():
                    yield to_return.strip()
                buffer = to_keep
            elif "." in token:
                is_post_period = True
                tokens_since_period = 0

            if is_post_period and tokens_since_period > TOKENS_TO_GENERATE_PAST_PERIOD:
                sentences = split_sentences(buffer)
                if len(sentences) > 1:
                    yield " ".join(sentences[:-1])
                    buffer = sentences[-1]
                is_post_period = False
                tokens_since_period = 0
            else:
                tokens_since_period += 1

        elif isinstance(token, FunctionFragment):
            function_name_buffer += token.name
            function_args_buffer += token.arguments
    to_return = buffer.strip()
    if to_return:
        # Check for text-based tool calls in the final buffer
        text_tool_calls = extract_text_tool_calls(to_return)
        if text_tool_calls:
            # Remove in reverse order so earlier indices stay valid
            for name, args, start, end in reversed(text_tool_calls):
                to_return = to_return[:start] + to_return[end:]
                if get_functions:
                    function_name_buffer = name
                    function_args_buffer = args
            to_return = to_return.strip()
            if to_return:
                yield to_return
        else:
            yield to_return
    if function_name_buffer and get_functions:
        yield FunctionCall(name=function_name_buffer, arguments=function_args_buffer)


async def stream_response_async(
    conversation_id: str,
    gen: AsyncIterable[Union[str, FunctionFragment]],
    get_functions: Literal[True, False] = False,
    sentry_span: Optional[Span] = None,
) -> AsyncGenerator[
    Union[str, FunctionCall],
    None,
]:  # tuple of message to send and whether it's the final message
    splitters = (".", ",", "?", "!", ";", ":", "—", "-", "(", ")", "[", "]", "}", " ")
    buffer = ""
    function_name_buffer = ""
    function_args_buffer = ""
    is_first = True
    async for token in gen:
        if is_first:
            if sentry_span:
                sentry_span.finish()
            is_first = False
        if not token:
            continue
        if isinstance(token, str):
            if buffer.endswith(splitters):
                yield buffer if buffer.endswith(" ") else buffer + " "
                buffer = token
            elif token.startswith(splitters):
                output = buffer + token[0]
                yield output if output.endswith(" ") else output + " "
                buffer = token[1:]
            else:
                buffer += token

        elif isinstance(token, FunctionFragment):
            function_name_buffer += token.name
            function_args_buffer += token.arguments
    if buffer != "":
        # Check for text-based tool calls in the final buffer
        text_tool_calls = extract_text_tool_calls(buffer)
        if text_tool_calls:
            # Remove in reverse order so earlier indices stay valid
            for name, args, start, end in reversed(text_tool_calls):
                buffer = buffer[:start] + buffer[end:]
                if get_functions:
                    function_name_buffer = name
                    function_args_buffer = args
        buffer = buffer.strip()
        if buffer:
            yield buffer + " "
    if function_name_buffer and get_functions:
        yield FunctionCall(name=function_name_buffer, arguments=function_args_buffer)
