import json,logging,time
class JsonFormatter(logging.Formatter):
 def format(self,record): return json.dumps({'ts':time.time(),'level':record.levelname,'logger':record.name,'message':record.getMessage()})
def configure_logging(): logging.basicConfig(level=logging.INFO,handlers=[logging.StreamHandler()],force=True); logging.getLogger().handlers[0].setFormatter(JsonFormatter())
