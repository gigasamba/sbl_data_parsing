"""classify_sfdc — pl-33(사용자 11-02) SFDC 문서 하나를 종류 라벨 하나로.
Caller: pipeline/load/classify.py classify_one() — the prompt text (this package prompt.md) goes as the system message.
output_schema is left out on purpose: a schema mismatch would trigger one automatic re-ask, and the user decided no retries (NULL instead)."""
from google.adk.agents import LlmAgent


def create_agent(model, tools):
    assert not tools, "classify_sfdc: pipeline agent takes no tools"
    return LlmAgent(name="classify_sfdc", model=model, mode="single_turn", instruction="",
                     description="SFDC 문서 종류 라벨 하나(pl-33)")
