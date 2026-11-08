"""应用工厂：启动不自动建表，以 Alembic 显式迁移数据库。"""
import logging
import time
import threading
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from uuid import uuid4
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from sqlalchemy import text, update
from sqlalchemy.exc import SQLAlchemyError
from app.api.v1.routes import router
from app.core.config import Settings
from app.core.security import SecretVault, hash_password
from app.db.session import make_engine, make_sessions
from app.core.body_limit import BodyLimitMiddleware

logger = logging.getLogger('agenttestlab')


def create_app(settings=None, *, test_engine=None):
    """test_engine 仅用于自动化测试；命令行启动始终使用配置中的 MySQL。"""
    settings = settings or Settings()
    engine = test_engine if test_engine is not None else make_engine(settings.database_url.get_secret_value())

    @asynccontextmanager
    async def lifespan(app):
        # 当前支持单进程部署；重启后将未完成调用标为中断，不伪装仍在运行。
        from app.models.entities import GenerationRun, DemoRun
        from app.models.platform import TestTask,TestResult,RagDocument,RagEvaluation,RagDataset
        with app.state.sessions() as db:
            db.execute(update(GenerationRun).where(GenerationRun.status=='generating').values(status='failed',error_code='interrupted'))
            db.execute(update(DemoRun).where(DemoRun.status=='running').values(status='failed'))
            db.execute(update(TestTask).where(TestTask.status.in_(['running','pause_requested','cancel_requested'])).values(status='interrupted',error_code='server_restarted'))
            db.execute(update(TestResult).where(TestResult.status=='running').values(status='error',error_code='execution_interrupted'))
            db.execute(update(RagDocument).where(RagDocument.status=='indexing').values(status='failed',error_code='index_interrupted'))
            db.execute(update(RagEvaluation).where(RagEvaluation.status=='running').values(status='failed',error_code='interrupted'))
            db.execute(update(RagDataset).where(RagDataset.status=='generating').values(status='failed',error_code='interrupted'))
            db.commit()
        yield
        await app.state.task_manager.shutdown()
        engine.dispose()

    app = FastAPI(title='AgentTestLab API', version='0.1.0', lifespan=lifespan)
    app.state.settings, app.state.engine = settings, engine
    app.state.sessions = make_sessions(engine)
    app.state.vault = SecretVault(settings.encryption_key.get_secret_value())
    app.state.dummy_hash = hash_password('nonexistent-account-timing-placeholder')
    app.state.auth_limits = defaultdict(deque)
    app.state.model_busy = False
    app.state.rag_busy = set()
    app.state.rag_guard = threading.Lock()
    from app.services.tasks import TaskManager
    app.state.task_manager = TaskManager(app)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                       allow_methods=['GET', 'POST', 'PUT', 'DELETE'], allow_headers=['Authorization', 'Content-Type'])
    app.add_middleware(BodyLimitMiddleware)

    @app.middleware('http')
    async def request_context(request: Request, call_next):
        request.state.request_id = str(uuid4())
        started = time.perf_counter()
        response = await call_next(request)
        response.headers['X-Request-ID'] = request.state.request_id
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'no-store'
        # 不记录 URL 参数、请求/响应体、headers 或异常原文。
        logger.info('request_id=%s method=%s status=%s duration_ms=%.2f',
                    request.state.request_id, request.method, response.status_code, (time.perf_counter()-started)*1000)
        return response

    def error_response(request, status, code, message, details=None, headers=None):
        return JSONResponse(status_code=status, headers=headers,
            content={'error': {'code': code, 'message': message, 'details': details},
                     'request_id': getattr(request.state, 'request_id', None)})

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error_response(request, exc.status_code, f'http_{exc.status_code}', str(exc.detail), headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # 不返回 Pydantic 的 input 和 ctx，避免密码、请求头等敏感字段回显。
        details = [{'field': '.'.join(map(str, e['loc'])), 'type': e['type']} for e in exc.errors()]
        return error_response(request, 422, 'validation_error', '输入格式不正确，请检查字段', details)

    @app.exception_handler(SQLAlchemyError)
    async def db_error(request, exc):
        logger.error('database_error request_id=%s type=%s', request.state.request_id, type(exc).__name__)
        return error_response(request, 503, 'database_unavailable', '数据库不可用或数据操作冲突')

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        logger.error('internal_error request_id=%s type=%s', request.state.request_id, type(exc).__name__)
        return error_response(request, 500, 'internal_error', '服务异常，请凭请求编号查看日志')

    @app.get('/health/live', tags=['health'])
    def live():
        return {'status': 'ok', 'version': '0.1.0'}

    @app.get('/health/ready', tags=['health'])
    def ready():
        # readiness 必须验证迁移表可读，不能只用端口或 SELECT 1。
        with engine.connect() as conn:
            conn.execute(text('SELECT version_num FROM alembic_version'))
            conn.execute(text('SELECT id FROM users LIMIT 1'))
        return {'database': 'ok', 'milvus': '请运行 scripts/verify_milvus.py 单独验证'}

    app.include_router(router)
    from app.api.v1.cases import router as cases_router
    app.include_router(cases_router)
    from app.api.v1.generation import router as generation_router
    app.include_router(generation_router)
    from app.api.v1.demo import router as demo_router
    app.include_router(demo_router)
    from app.api.v1.tasks import router as tasks_router
    app.include_router(tasks_router)
    from app.api.v1.rag import router as rag_router
    app.include_router(rag_router)
    from app.api.v1.security import router as security_router
    from app.api.v1.analysis import router as analysis_router
    from app.api.v1.management import router as management_router
    app.include_router(security_router)
    app.include_router(analysis_router)
    app.include_router(management_router)
    return app
