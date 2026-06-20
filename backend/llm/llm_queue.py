import asyncio, time
QUEUE=asyncio.Queue(); COUNTER=0
async def enqueue(job):
    global COUNTER
    COUNTER+=1; fut=asyncio.get_event_loop().create_future()
    await QUEUE.put((COUNTER,time.time(),job,fut)); return await fut
async def worker():
    while True:
        qid,t,job,fut=await QUEUE.get()
        try: fut.set_result({"queue_id":qid,"queue_wait_ms":int((time.time()-t)*1000),"text":await job(),"error":None})
        except Exception as e: fut.set_result({"queue_id":qid,"queue_wait_ms":int((time.time()-t)*1000),"text":None,"error":str(e)})
        finally: QUEUE.task_done()
