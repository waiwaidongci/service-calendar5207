from fastapi import APIRouter,Depends
from src.config.database import database
from src.controllers.auth import current,editor
from src.schemas.requests import SimInput,SimRerunInput
from src.services.sim import create_sim,rerun_sim,list_sims,get_sim
router=APIRouter()
@router.get('/sims')
def sims(db=Depends(database),u=Depends(current)): return list_sims(db)
@router.post('/sims')
def create(b:SimInput,db=Depends(database),u=Depends(editor)): return create_sim(db,u,b)
@router.get('/sims/{id}')
def detail(id:int,db=Depends(database),u=Depends(current)): return get_sim(db,id)
@router.post('/sims/{id}/rerun')
def rerun(id:int,b:SimRerunInput,db=Depends(database),u=Depends(editor)): return rerun_sim(db,u,id,b)
