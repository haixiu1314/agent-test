from types import SimpleNamespace
from app.adapters.base import AgentAdapter, AgentResponse
from app.services.demo import chat


class EnterpriseAdapter(AgentAdapter):
    def __init__(self,config,key,defect='none',knowledge_retriever=None):
        self.config,self.key,self.defect=config,key,defect
        self.knowledge_retriever=knowledge_retriever

    async def invoke(self,input_text,history):
        body=SimpleNamespace(input=input_text,history=[SimpleNamespace(**h) for h in history],defect=self.defect)
        result=await chat(self.config,self.key,body,self.knowledge_retriever) if self.knowledge_retriever else await chat(self.config,self.key,body)
        usage={}
        supplied=[u for u in result['usage'] if u]
        if supplied:
            for key in ['input_tokens','output_tokens','total_tokens']:
                values=[u.get(key) for u in supplied if isinstance(u.get(key),int)]
                if values:usage[key]=sum(values)
        contexts=[s['text'] for e in result['events'] if e.get('name')=='knowledge_search'
                  for s in e.get('result',{}).get('snippets',[])]
        return AgentResponse(result['output'],None,1,result['events'],True,usage,contexts)
