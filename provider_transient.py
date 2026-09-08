from dataclasses import dataclass
@dataclass(frozen=True)
class TransientDiscoveryResult:
 provider:str
 provider_record_id:str
 display_name:str|None=None
 formatted_address:str|None=None
 website_uri:str|None=None
 phone:str|None=None
 rating:float|None=None
 user_rating_count:int|None=None
 def durable_ref(self): return {'provider':self.provider,'provider_record_id':self.provider_record_id}
