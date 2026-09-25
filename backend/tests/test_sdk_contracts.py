from types import SimpleNamespace
from app.schemas import SummaryData
from app.summaries import OpenAISummaryProvider, GeminiSummaryProvider

RESULT=SummaryData(research_question=None,methods=None,key_findings=[],limitations=[],takeaway=None)
PAPER=SimpleNamespace(title='Title',journal=None,publication_year=None,abstract='Verified abstract')


def test_openai_responses_sdk_contract(monkeypatch):
    calls=[]
    class Client:
        def __init__(self,**kwargs):
            assert kwargs['max_retries']==0
            self.responses=self
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def parse(self,**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(status='completed',output_parsed=RESULT,usage=None)
    monkeypatch.setattr('openai.OpenAI',Client)
    result,_=OpenAISummaryProvider().summarize(PAPER)
    assert result==RESULT and calls[0]['text_format'] is SummaryData
    assert calls[0]['max_output_tokens']==1000 and calls[0]['store'] is False


def test_gemini_official_sdk_types(monkeypatch):
    calls=[]
    class Client:
        def __init__(self,**kwargs):
            assert kwargs['http_options'].retry_options.attempts==1
            self.models=self
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def generate_content(self,**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(candidates=[SimpleNamespace(finish_reason='STOP')],text=RESULT.model_dump_json(),usage_metadata=None)
    monkeypatch.setattr('google.genai.Client',Client)
    result,_=GeminiSummaryProvider().summarize(PAPER)
    assert result==RESULT
    config=calls[0]['config']
    assert config.response_mime_type=='application/json' and config.response_json_schema['additionalProperties'] is False
