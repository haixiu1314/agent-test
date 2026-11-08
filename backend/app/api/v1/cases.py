from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select, delete
from app.api.v1.routes import current_user, database
from app.models.entities import TestSuite, TestSuiteVersion, TestCase, Project
from app.schemas.cases import SuiteInput, SuitePublic, CaseCreate, CaseUpdate, CasePublic, ImportBatch, FileImport
from app.services.catalog import project_for_user, log_operation, paginate
from app.services.cases import suite_for_user, suite_dict, case_dict, snapshot, add_cases, import_cases, export_cases

router = APIRouter(prefix='/api/v1', tags=['test-cases'])


def audit(db, user, request, action, resource):
    log_operation(db,user,action,resource,request.state.request_id)
    db.commit()


@router.get('/suites')
def suites(project_id: str, user=Depends(current_user), db=Depends(database)):
    project_for_user(db,project_id,user)
    rows=db.scalars(select(TestSuite).where(TestSuite.project_id==project_id).order_by(TestSuite.created_at.desc())).all()
    return {'items':[suite_dict(db,r) for r in rows]}


@router.post('/suites', status_code=201, response_model=SuitePublic)
def create_suite(body:SuiteInput,request:Request,user=Depends(current_user),db=Depends(database)):
    project_for_user(db,body.project_id,user)
    item=TestSuite(**body.model_dump(exclude={'expected_revision'}))
    db.add(item)
    db.flush()
    snapshot(db,item,False)
    audit(db,user,request,'suite.create',item.id)
    return suite_dict(db,item)


@router.put('/suites/{suite_id}',response_model=SuitePublic)
def update_suite(suite_id:str,body:SuiteInput,request:Request,user=Depends(current_user),db=Depends(database)):
    if body.expected_revision is None:raise HTTPException(422,'需要套件版本')
    item=suite_for_user(db,suite_id,user,body.expected_revision)
    if body.project_id!=item.project_id:raise HTTPException(422,'不允许移动套件')
    item.name,item.description=body.name,body.description
    snapshot(db,item)
    audit(db,user,request,'suite.update',item.id)
    return suite_dict(db,item)


@router.delete('/suites/{suite_id}',status_code=204)
def delete_suite(suite_id:str,request:Request,expected_revision:int=Query(ge=1),user=Depends(current_user),db=Depends(database)):
    item=suite_for_user(db,suite_id,user,expected_revision)
    from app.models.platform import TestTask
    if db.scalar(select(TestTask.id).where(TestTask.suite_id==suite_id).limit(1)):
        raise HTTPException(409,'套件已有关联任务，请保留快照')
    db.execute(delete(TestCase).where(TestCase.suite_id==suite_id))
    db.execute(delete(TestSuiteVersion).where(TestSuiteVersion.suite_id==suite_id))
    db.delete(item)
    audit(db,user,request,'suite.delete',suite_id)


@router.get('/suites/{suite_id}/versions')
def versions(suite_id:str,page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100),user=Depends(current_user),db=Depends(database)):
    suite_for_user(db,suite_id,user)
    rows,count=paginate(db,select(TestSuiteVersion).where(TestSuiteVersion.suite_id==suite_id).order_by(TestSuiteVersion.revision.desc()),page,page_size)
    return {'items':[{'revision':r.revision,'snapshot':r.snapshot,'created_at':r.created_at} for r in rows],'total':count}


@router.get('/cases')
def cases(suite_id:str,page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100),test_type:str|None=None,user=Depends(current_user),db=Depends(database)):
    suite_for_user(db,suite_id,user)
    stmt=select(TestCase).where(TestCase.suite_id==suite_id).order_by(TestCase.created_at,TestCase.id)
    if test_type:stmt=stmt.where(TestCase.test_type==test_type)
    rows,count=paginate(db,stmt,page,page_size)
    return {'items':[case_dict(r) for r in rows],'total':count}


@router.post('/cases',status_code=201,response_model=CasePublic)
def create_case(body:CaseCreate,request:Request,expected_revision:int=Query(ge=1),user=Depends(current_user),db=Depends(database)):
    suite=suite_for_user(db,body.suite_id,user,expected_revision)
    from app.schemas.cases import CaseDraft
    rows=add_cases(db,suite,[CaseDraft.model_validate(body.model_dump(exclude={'suite_id'}))])
    audit(db,user,request,'case.create',suite.id)
    return case_dict(rows[0])


def owned_case(db,case_id,user):
    item=db.get(TestCase,case_id)
    if not item:raise HTTPException(404,'用例不存在')
    suite=suite_for_user(db,item.suite_id,user)
    db.refresh(item)
    return item,suite


@router.put('/cases/{case_id}',response_model=CasePublic)
def update_case(case_id:str,body:CaseUpdate,request:Request,user=Depends(current_user),db=Depends(database)):
    item,suite=owned_case(db,case_id,user)
    if item.revision!=body.expected_revision:raise HTTPException(409,'用例版本已变化')
    for k,v in body.model_dump(mode='json',exclude={'expected_revision'}).items():setattr(item,k,v)
    item.revision+=1
    snapshot(db,suite)
    audit(db,user,request,'case.update',item.id)
    return case_dict(item)


@router.delete('/cases/{case_id}',status_code=204)
def delete_case(case_id:str,request:Request,expected_revision:int=Query(ge=1),user=Depends(current_user),db=Depends(database)):
    item,suite=owned_case(db,case_id,user)
    if item.revision!=expected_revision:raise HTTPException(409,'用例版本已变化')
    db.delete(item)
    snapshot(db,suite)
    audit(db,user,request,'case.delete',case_id)


@router.post('/suites/{suite_id}/import')
def import_file(suite_id:str,body:FileImport,request:Request,user=Depends(current_user),db=Depends(database)):
    drafts=import_cases(body.content,body.format)
    suite=suite_for_user(db,suite_id,user,body.expected_revision)
    rows=add_cases(db,suite,drafts,'import')
    audit(db,user,request,'case.import',suite.id)
    return {'imported':len(rows),'revision':suite.revision}


@router.get('/suites/{suite_id}/export')
def export_file(suite_id:str,format:str=Query('json',pattern='^(json|csv)$'),user=Depends(current_user),db=Depends(database)):
    suite_for_user(db,suite_id,user)
    rows=db.scalars(select(TestCase).where(TestCase.suite_id==suite_id).order_by(TestCase.id)).all()
    return {'format':format,'content':export_cases(rows,format)}
