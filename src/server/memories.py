"""Owner-scoped memory routes mounted by the existing API."""
from typing import Annotated
from fastapi import APIRouter,Depends,Request,HTTPException,Path
from pydantic import BaseModel,ConfigDict,Field
from src.server.session import require_user

MemoryID=Annotated[int,Path(ge=1,le=9223372036854775807)]


class Edit(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    value:str=Field(min_length=1,max_length=6000)
    revision:int=Field(ge=1,le=9223372036854775807)


class Revision(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    revision:int=Field(ge=1,le=9223372036854775807)


class Automatic(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    automatic_enabled:bool
    revision:int=Field(ge=0,le=9223372036854775807)


def routes(origin_check):
    router=APIRouter(prefix='/memories',tags=['memories'])
    def store():
        from src.memory.store import memory_store
        return memory_store
    from src.memory import management
    @router.get('')
    def listing(request:Request,include_deleted:bool=False,user:str=Depends(require_user)):
        if set(request.query_params)-{'include_deleted'}:raise HTTPException(422,'不支持的查询参数')
        return management.listing(store(),user,include_deleted)
    @router.get('/settings')
    def settings(request:Request,user:str=Depends(require_user)):
        if request.query_params:raise HTTPException(422,'不支持的查询参数')
        return management.settings(store(),user)
    @router.patch('/settings',dependencies=[Depends(origin_check)])
    def update_settings(req:Automatic,user:str=Depends(require_user)):
        return management.set_settings(store(),user,req.automatic_enabled,req.revision)
    @router.get('/{identity}')
    def detail(identity:MemoryID,request:Request,user:str=Depends(require_user)):
        if request.query_params:raise HTTPException(422,'不支持的查询参数')
        return management.detail(store(),user,identity)
    @router.patch('/{identity}',dependencies=[Depends(origin_check)])
    def edit(identity:MemoryID,req:Edit,user:str=Depends(require_user)):
        try:return management.mutate(store(),user,identity,req.revision,req.value)
        except ValueError as error:raise HTTPException(422,str(error)) from error
    @router.delete('/{identity}',dependencies=[Depends(origin_check)])
    def delete(identity:MemoryID,req:Revision,user:str=Depends(require_user)):
        return management.mutate(store(),user,identity,req.revision,delete=True)
    return router
