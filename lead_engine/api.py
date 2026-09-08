from fastapi import FastAPI
from health import liveness, readiness
app=FastAPI(title='LeadPro API')
@app.get('/health/live')
def live(): return liveness()
@app.get('/health/ready')
def ready(): return readiness()
