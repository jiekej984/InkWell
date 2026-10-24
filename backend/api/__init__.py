"""API 路由聚合。

各业务模块的路由在对应阶段逐个接入（§九 里程碑）。
当前挂载 ``system``（1.3）、``tasks``（2.12 / #45）、``projects``（2.1 / #2~#9）、
``volumes``（2.2 / #10~#17、#22）、``maintenance``（2.5 / #43）、
``chapters``（2.3 / #18~#21 与图片上传）、``files``（2.3 / #37 签名）、
``drafts``（2.4 暂存）、``versions``（2.6 / #23~#27）、``documents``（2.7 / #28~#30）、
``trash``（2.8 / #39~#41）、``backup``（2.9 / #32~#34）、``export``（2.10 / #35）、
``search``（2.11 / #31）。
"""

from fastapi import APIRouter

from .backup import router as backup_router
from .chapters import router as chapters_router
from .characters import router as characters_router
from .documents import router as documents_router
from .drafts import router as drafts_router
from .export import router as export_router
from .files import api_router as files_router
from .maintenance import router as maintenance_router
from .organizations import router as organizations_router
from .projects import router as projects_router
from .search import router as search_router
from .system import router as system_router
from .tasks import router as tasks_router
from .trash import router as trash_router
from .versions import router as versions_router
from .volumes import router as volumes_router

api_router = APIRouter()
api_router.include_router(system_router)
api_router.include_router(tasks_router)
api_router.include_router(projects_router)
api_router.include_router(volumes_router)
api_router.include_router(chapters_router)
api_router.include_router(files_router)
api_router.include_router(drafts_router)
api_router.include_router(versions_router)
api_router.include_router(documents_router)
api_router.include_router(trash_router)
api_router.include_router(backup_router)
api_router.include_router(export_router)
api_router.include_router(search_router)
api_router.include_router(maintenance_router)
# V2.0 角色库（任务 5.3）
api_router.include_router(characters_router)
api_router.include_router(organizations_router)
