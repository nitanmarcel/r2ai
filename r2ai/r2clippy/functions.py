from typing import Dict, List

from instructor.function_calls import OpenAISchema
from pydantic import Field, computed_field
from pydantic_core import ValidationError

from r2ai.pipe import get_r2_inst, r2lang
from r2ai.r2clippy.chunks import get_chunk, add_chunk, size
from r2ai import LOGGER

class _FunctionStorage:
    def __init__(self):
        self._storage = []

    def store(self):
        def decorator(cls):
            if cls not in self._storage:
                self._storage.append(cls)
            return cls
        return decorator

    def get_all(self) -> List[OpenAISchema]:
        return self._storage


FunctionStorage = _FunctionStorage()


@FunctionStorage.store()
class R2Cmd(OpenAISchema):
    """runs commands in radare2. You can run it multiple times or chain commands
        with pipes/semicolons. You can also use r2 interpreters to run scripts using
        the `#`, '#!', etc. commands. The output could be long, so try to use filters
        if possible or limit. This is your preferred tool
    """
    command: str = Field(description="radare2 command to run")

    @computed_field
    def result(self) -> str:
        r2 = get_r2_inst()
        print("Running %s" % self.command)
        res = r2.cmd(self.command)
        print(res)
        add_chunk(res)
        res = get_chunk()
        chunk_size = size()
        if chunk_size > 0:
            res+= f"\nChunked message. Remaining chunks: {chunk_size}. Use RetriveChunk to retrive the next chunk."
        LOGGER.getChild("auto").info("Response has been chunked. Nr of chunks: %s", chunk_size)
        return res


@FunctionStorage.store()
class PythonCmd(OpenAISchema):
    """runs a python snippet or script"""
    snippet: str = Field(description="python snippet to run")

    @computed_field
    def result(self) -> str:
        with open('r2ai_tmp.py', 'w') as f:
            f.write(self.snippet)
            print('\x1b[1;32mRunning \x1b[4m' + "python code" + '\x1b[0m')
            print(self.snippet)
            r2lang.cmd('#!python r2ai_tmp.py > $tmp')
            res = r2lang.cmd('cat $tmp')
            add_chunk(res)
            res = get_chunk()
            chunk_size = size()
            if chunk_size > 0:
                res+= f"\nChunked message. Remaining chunks: {chunk_size}. Use RetriveChunk to retrive the next chunk."
            r2lang.cmd('rm r2ai_tmp.py')
            print(res)
            return res

@FunctionStorage.store()
class RetriveChunk(OpenAISchema):
    """gets a chunk of a chunked message."""

    @computed_field
    def result(self) -> str:
        res = get_chunk()
        chunk_size = size()
        if chunk_size > 0:
            res+=f"\nChunked message. Remaining chunks: {chunk_size}. Use RetriveChunk to retrive the next chunk."
        LOGGER.getChild("auto").info("Remaining chunks: %s", chunk_size)
        return res

def get_ai_tools() -> Dict[str, str]:
    tools = []
    for i in FunctionStorage.get_all():
        tools.append(
            {
                "type": "function",
                "function": i.openai_schema
            }
        )
    return tools

def validate_ai_tool(arguments: Dict[str, str]) -> OpenAISchema:
    tools = FunctionStorage.get_all()
    original_exception = None
    for i, t in enumerate(tools):
        try:
            return t.model_validate(arguments)
        except ValidationError as e:
            if not original_exception:
                original_exception = e
            if i == len(tools) - 1:
                raise original_exception
            continue
