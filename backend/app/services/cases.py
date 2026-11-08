"""套件事务、不可变快照和可往返的用例交换格式。"""
import csv
import io
import json
from fastapi import HTTPException
from sqlalchemy import select, func
from app.models.entities import TestSuite, TestSuiteVersion, TestCase
from app.schemas.cases import CaseDraft
from app.services.catalog import project_for_user


def suite_for_user(db, suite_id, user, revision=None):
    item = db.scalar(select(TestSuite).where(TestSuite.id == suite_id).with_for_update())
    if not item:
        raise HTTPException(404, '测试套件不存在')
    project_for_user(db, item.project_id, user)
    if revision is not None and item.revision != revision:
        raise HTTPException(409, '套件已变化，请刷新后重试')
    return item


def case_dict(item):
    return {k: getattr(item, k) for k in [*CaseDraft.model_fields, 'id', 'suite_id', 'revision', 'source', 'generation_run_id', 'created_at', 'updated_at']}


def suite_dict(db, item):
    result = {k: getattr(item, k) for k in ['id','project_id','name','description','revision','created_at','updated_at']}
    result['case_count'] = db.scalar(select(func.count()).select_from(TestCase).where(TestCase.suite_id == item.id))
    return result


def snapshot(db, suite, increment=True):
    if increment:
        suite.revision += 1
    db.flush()
    rows = db.scalars(select(TestCase).where(TestCase.suite_id == suite.id).order_by(TestCase.id)).all()
    # 显式上限保护每次保存的快照体积。
    if len(rows) > 1000:
        raise HTTPException(422, '每个套件最多 1000 条用例')
    cases = [CaseDraft.model_validate(case_dict(r), extra='ignore').model_dump(mode='json') | {'id':r.id,'revision':r.revision} for r in rows]
    if len(json.dumps(cases,ensure_ascii=False).encode('utf-8'))>4*1024*1024:
        raise HTTPException(422,'套件快照超过 4 MiB，请拆分套件')
    db.add(TestSuiteVersion(suite_id=suite.id, revision=suite.revision,
        snapshot={'name':suite.name,'description':suite.description,'cases':cases}))


def add_cases(db, suite, cases, source='manual', run_id=None):
    rows = [TestCase(suite_id=suite.id, **c.model_dump(mode='json'), source=source, generation_run_id=run_id) for c in cases]
    db.add_all(rows)
    snapshot(db, suite)
    return rows


def export_cases(cases, format):
    records = [CaseDraft.model_validate(case_dict(c), extra='ignore').model_dump(mode='json') for c in cases]
    if format == 'json':
        return json.dumps(records, ensure_ascii=False, indent=2)
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=list(CaseDraft.model_fields))
    writer.writeheader()
    for row in records:
        # 每个单元格采用 JSON 编码，既保留类型也避免电子表格公式执行。
        writer.writerow({k:json.dumps(v, ensure_ascii=False) for k,v in row.items()})
    return output.getvalue()


def import_cases(content, format):
    try:
        if format == 'json':
            rows = json.loads(content)
        else:
            reader = csv.DictReader(io.StringIO(content))
            if reader.fieldnames != list(CaseDraft.model_fields):
                raise ValueError('columns')
            rows = [{k:json.loads(v) for k,v in row.items()} for row in reader]
        if not isinstance(rows,list) or not 1 <= len(rows) <= 100:
            raise ValueError('count')
        return [CaseDraft.model_validate(row) for row in rows]
    except (ValueError, TypeError, csv.Error):
        raise HTTPException(422, '导入失败：需为 1–100 条完整用例；CSV 单元格使用 JSON 编码') from None
